"""Workflow engine service. The only writer of stage state.

Concurrency: every transition locks its workflow execution row first, then the stage row, so
transitions within one execution are serialized. Optional expected_version gives callers an
optimistic check on top of the lock.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.projects.models import Project, ProjectMember
from app.workflows.compiler import CompiledWorkflow, compile_workflow
from app.workflows.models import (
    StageExecution,
    StageTransition,
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowVersion,
)
from app.workflows.state_machine import (
    SATISFIES_DEPENDENCY,
    ActorType,
    InvalidTransition,
    StageStatus,
    check_transition,
)
from app.workflows.work import WORK_FUNCTIONS, WorkContext


def publish_version(db: Session, raw: dict[str, Any]) -> WorkflowVersion:
    """Compile and store a new immutable version. Nothing is stored if compilation fails."""
    compiled: CompiledWorkflow = compile_workflow(raw, known_work=set(WORK_FUNCTIONS))
    key = compiled.spec["key"]
    definition = db.execute(select(WorkflowDefinition).where(WorkflowDefinition.key == key)).scalar_one_or_none()
    if definition is None:
        definition = WorkflowDefinition(id=uuid7(), key=key, name=compiled.spec["name"])
        db.add(definition)
        db.flush()
    latest = db.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.definition_id == definition.id)
        .order_by(WorkflowVersion.version.desc())
    ).scalars().first()
    version = WorkflowVersion(
        id=uuid7(),
        definition_id=definition.id,
        version=(latest.version + 1) if latest else 1,
        spec_json=compiled.spec,
        sha256=compiled.sha256,
    )
    db.add(version)
    db.commit()
    return version


def _project_member(db: Session, user: User, project_id: uuid.UUID) -> Project:
    row = db.execute(
        select(Project, ProjectMember.project_role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == user.id)
    ).one_or_none()
    if row is None:
        raise not_found()
    return row[0]


def start_execution(db: Session, user: User, *, project_id: uuid.UUID, workflow_version_id: uuid.UUID) -> WorkflowExecution:
    project = _project_member(db, user, project_id)
    role = db.execute(
        select(ProjectMember.project_role).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    ).scalar_one()
    if role != "project_owner":
        raise AppError(403, "not_permitted", "Only the project owner can start a workflow")

    version = db.get(WorkflowVersion, workflow_version_id)
    if version is None:
        raise AppError(404, "unknown_workflow_version", "Workflow version does not exist")
    compiled = compile_workflow(version.spec_json, known_work=set(WORK_FUNCTIONS))
    stage_specs = {s["id"]: s for s in version.spec_json["stages"]}

    execution = WorkflowExecution(
        id=uuid7(),
        project_id=project.id,
        workflow_version_id=version.id,
        organization_id=project.organization_id,
        status="RUNNING",
        created_by=user.id,
    )
    db.add(execution)
    db.flush()
    for stage_id in compiled.order:
        is_root = not compiled.graph[stage_id]
        status = StageStatus.READY if is_root else StageStatus.NOT_STARTED
        db.add(
            StageExecution(
                id=uuid7(),
                workflow_execution_id=execution.id,
                stage_key=stage_id,
                status=status.value,
                version=0,
            )
        )
    db.flush()
    append_event(
        db,
        chain_key=org_chain(project.organization_id),
        event_type="workflow.started",
        actor_type="human",
        actor_id=str(user.id),
        organization_id=project.organization_id,
        project_id=project.id,
        payload={"workflow_key": version.spec_json["key"], "version": version.id.hex, "stages": len(stage_specs)},
    )
    db.commit()
    return execution


def _lock_stage(db: Session, execution_id: uuid.UUID, stage_key: str) -> tuple[WorkflowExecution, StageExecution]:
    execution = db.execute(
        select(WorkflowExecution).where(WorkflowExecution.id == execution_id).with_for_update()
    ).scalar_one_or_none()
    if execution is None:
        raise not_found()
    stage = db.execute(
        select(StageExecution)
        .where(StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == stage_key)
        .with_for_update()
    ).scalar_one_or_none()
    if stage is None:
        raise AppError(404, "unknown_stage", "Stage does not exist in this workflow")
    return execution, stage


def transition_stage(
    db: Session,
    *,
    execution_id: uuid.UUID,
    stage_key: str,
    to_status: StageStatus,
    actor: ActorType,
    actor_id: str | None = None,
    expected_version: int | None = None,
    reason: str = "",
    output: dict[str, Any] | None = None,
) -> StageExecution:
    """Apply one legal transition, with its log row, audit event and readiness update, atomically."""
    execution, stage = _lock_stage(db, execution_id, stage_key)
    if expected_version is not None and expected_version != stage.version:
        raise AppError(409, "version_conflict", "The stage changed; reload and try again")

    from_status = StageStatus(stage.status)
    try:
        check_transition(from_status, to_status, actor)
    except InvalidTransition as exc:
        raise AppError(409, "invalid_transition", str(exc)) from exc

    if to_status is StageStatus.APPROVED:
        raise AppError(409, "approval_required", "Approval needs the approval engine (Milestone 4)")

    stage.status = to_status.value
    stage.version += 1
    if output is not None:
        stage.output_json = output
    if to_status is StageStatus.FAILED:
        stage.failure_reason = reason[:300]
    db.add(
        StageTransition(
            stage_execution_id=stage.id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor_type=actor.value,
            actor_id=actor_id,
            reason=reason[:300],
        )
    )
    append_event(
        db,
        chain_key=org_chain(execution.organization_id),
        event_type=f"stage.{to_status.value.lower()}",
        actor_type=actor.value,
        actor_id=actor_id,
        organization_id=execution.organization_id,
        project_id=execution.project_id,
        payload={"workflow_execution": execution.id.hex, "stage": stage_key, "from": from_status.value},
    )
    db.flush()
    if to_status in SATISFIES_DEPENDENCY:
        _refresh_readiness(db, execution)
    db.commit()
    return stage


def _refresh_readiness(db: Session, execution: WorkflowExecution) -> None:
    """NOT_STARTED -> READY when every dependency is APPROVED or SKIPPED (system edge)."""
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    graph = {s["id"]: s["depends_on"] for s in version.spec_json["stages"]}
    stages = {
        s.stage_key: s
        for s in db.execute(
            select(StageExecution).where(StageExecution.workflow_execution_id == execution.id)
        ).scalars()
    }
    for key, deps in graph.items():
        stage = stages[key]
        if stage.status != StageStatus.NOT_STARTED.value:
            continue
        if all(StageStatus(stages[d].status) in SATISFIES_DEPENDENCY for d in deps):
            stage.status = StageStatus.READY.value
            stage.version += 1
            db.add(
                StageTransition(
                    stage_execution_id=stage.id,
                    from_status=StageStatus.NOT_STARTED.value,
                    to_status=StageStatus.READY.value,
                    actor_type=ActorType.SYSTEM.value,
                    reason="dependencies satisfied",
                )
            )
            append_event(
                db,
                chain_key=org_chain(execution.organization_id),
                event_type="stage.ready",
                actor_type=ActorType.SYSTEM.value,
                organization_id=execution.organization_id,
                project_id=execution.project_id,
                payload={"workflow_execution": execution.id.hex, "stage": key},
            )


def run_deterministic_stage(db: Session, *, execution_id: uuid.UUID, stage_key: str) -> StageExecution:
    """Run one stage's deterministic work function through the state machine.

    No AI is involved. Output is checked against the stage's required keys; a failed check moves
    the stage to BLOCKED. The stage ends in AWAITING_HUMAN_REVIEW: approval is Milestone 4.
    Each step below is its own locked transition, so the stage is never left half-done silently.
    """
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise not_found()
    current = db.execute(
        select(StageExecution).where(
            StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == stage_key
        )
    ).scalar_one_or_none()
    if current is None:
        raise AppError(404, "unknown_stage", "Stage does not exist in this workflow")

    version = db.get(WorkflowVersion, execution.workflow_version_id)
    spec = next(s for s in version.spec_json["stages"] if s["id"] == stage_key)
    project = db.get(Project, execution.project_id)

    if current.status == StageStatus.READY.value:
        transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                         to_status=StageStatus.RUNNING, actor=ActorType.SYSTEM)
    context = WorkContext(
        project_name=project.name,
        project_description=project.description,
        project_type=project.project_type,
    )
    try:
        output = WORK_FUNCTIONS[spec["work"]](context)
    except Exception as exc:  # noqa: BLE001 - any work failure must be recorded as FAILED, not hidden
        return transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                to_status=StageStatus.FAILED, actor=ActorType.SYSTEM,
                                reason=f"work failed: {type(exc).__name__}")

    transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                     to_status=StageStatus.AI_COMPLETED, actor=ActorType.SYSTEM, output=output)
    transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                     to_status=StageStatus.VALIDATING, actor=ActorType.SYSTEM)
    missing = [k for k in spec["output_required_keys"] if k not in output]
    if missing:
        return transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                to_status=StageStatus.BLOCKED, actor=ActorType.SYSTEM,
                                reason=f"output missing keys: {', '.join(missing)}")
    return transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                            to_status=StageStatus.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM)


def execution_view(db: Session, user: User, execution_id: uuid.UUID) -> dict[str, Any]:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise not_found()
    _project_member(db, user, execution.project_id)  # not_found when the caller is not a member
    stages = db.execute(
        select(StageExecution).where(StageExecution.workflow_execution_id == execution.id)
    ).scalars()
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    order = [s["id"] for s in version.spec_json["stages"]]
    by_key = {s.stage_key: s for s in stages}
    return {
        "id": str(execution.id),
        "project_id": str(execution.project_id),
        "status": execution.status,
        "workflow": {"key": version.spec_json["key"], "name": version.spec_json["name"]},
        "stages": [
            {"key": k, "name": next(s["name"] for s in version.spec_json["stages"] if s["id"] == k),
             "status": by_key[k].status, "version": by_key[k].version}
            for k in order
        ],
    }
