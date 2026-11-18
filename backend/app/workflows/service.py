"""Workflow engine service. The only writer of stage state.

Concurrency: every transition locks its workflow execution row first, then the stage row, so
transitions within one execution are serialized. Optional expected_version gives callers an
optimistic check on top of the lock.

Atomicity: callers that combine several transitions (an approval, a rework run) pass commit=False
and commit once at the end. Any error rolls the whole unit back.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approvals.models import ChangeRequest
from app.artifacts import service as artifacts
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.config import Settings, get_settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.projects.models import Project, ProjectMember
from app.providers import service as providers
from app.providers.tasks import AI_TASKS, is_ai_task
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
from app.workflows.work import KNOWN_WORK, WORK_FUNCTIONS, WorkContext

MAX_REWORK_LOOPS = 3


def publish_version(db: Session, raw: dict[str, Any]) -> WorkflowVersion:
    """Compile and store a new immutable version. Nothing is stored if compilation fails."""
    compiled: CompiledWorkflow = compile_workflow(raw, known_work=set(KNOWN_WORK))
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


def project_role(db: Session, user: User, project_id: uuid.UUID) -> str | None:
    return db.execute(
        select(ProjectMember.project_role).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    ).scalar_one_or_none()


def stage_spec(version: WorkflowVersion, stage_key: str) -> dict[str, Any]:
    spec = next((s for s in version.spec_json["stages"] if s["id"] == stage_key), None)
    if spec is None:
        raise AppError(404, "unknown_stage", "Stage does not exist in this workflow")
    return spec


def start_execution(db: Session, user: User, *, project_id: uuid.UUID, workflow_version_id: uuid.UUID) -> WorkflowExecution:
    role = project_role(db, user, project_id)
    if role is None:
        raise not_found()
    if role != "project_owner":
        raise AppError(403, "not_permitted", "Only the project owner can start a workflow")
    project = db.get(Project, project_id)

    version = db.get(WorkflowVersion, workflow_version_id)
    if version is None:
        raise AppError(404, "unknown_workflow_version", "Workflow version does not exist")
    compiled = compile_workflow(version.spec_json, known_work=set(KNOWN_WORK))

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
        status = StageStatus.READY if not compiled.graph[stage_id] else StageStatus.NOT_STARTED
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
        payload={"workflow_key": version.spec_json["key"], "version": version.id.hex},
    )
    db.commit()
    return execution


def lock_stage(db: Session, execution_id: uuid.UUID, stage_key: str) -> tuple[WorkflowExecution, StageExecution]:
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
    approval_satisfied: bool = False,
    commit: bool = True,
) -> StageExecution:
    """Apply one legal transition with its log row, audit event and readiness update.

    APPROVED is reachable only with approval_satisfied=True, which the approval service sets after
    it has verified the policy inside the same locked transaction.
    AI_COMPLETED with output stores that output as a new artifact version.
    """
    execution, stage = lock_stage(db, execution_id, stage_key)
    if expected_version is not None and expected_version != stage.version:
        raise AppError(409, "version_conflict", "The stage changed; reload and try again")

    from_status = StageStatus(stage.status)
    try:
        check_transition(from_status, to_status, actor)
    except InvalidTransition as exc:
        raise AppError(409, "invalid_transition", str(exc)) from exc

    if to_status is StageStatus.APPROVED and not approval_satisfied:
        raise AppError(409, "approval_required", "A stage is approved only by a satisfied approval policy")

    stage.status = to_status.value
    stage.version += 1
    if output is not None:
        stage.output_json = output
    if to_status is StageStatus.AI_COMPLETED and output is not None:
        artifacts.create_version(
            db,
            project_id=execution.project_id,
            stage_execution_id=stage.id,
            kind=stage_key,
            content=output,
        )
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
        refresh_readiness(db, execution)
    if commit:
        db.commit()
    return stage


def stage_rows(db: Session, execution_id: uuid.UUID) -> dict[str, StageExecution]:
    return {
        s.stage_key: s
        for s in db.execute(
            select(StageExecution).where(StageExecution.workflow_execution_id == execution_id)
        ).scalars()
    }


def dependencies_satisfied(db: Session, execution: WorkflowExecution, stage_key: str) -> bool:
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    stages = stage_rows(db, execution.id)
    return all(
        StageStatus(stages[d].status) in SATISFIES_DEPENDENCY
        for d in stage_spec(version, stage_key)["depends_on"]
    )


def refresh_readiness(db: Session, execution: WorkflowExecution) -> None:
    """NOT_STARTED -> READY when every dependency is APPROVED or SKIPPED (system edge)."""
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    stages = stage_rows(db, execution.id)
    for spec in version.spec_json["stages"]:
        stage = stages[spec["id"]]
        if stage.status != StageStatus.NOT_STARTED.value:
            continue
        if all(StageStatus(stages[d].status) in SATISFIES_DEPENDENCY for d in spec["depends_on"]):
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
                payload={"workflow_execution": execution.id.hex, "stage": spec["id"]},
            )


def _produce(
    db: Session,
    *,
    execution: WorkflowExecution,
    stage_key: str,
    spec: dict[str, Any],
    context: WorkContext,
    settings: Settings,
    transport: Any,
) -> dict[str, Any]:
    """Run the stage's work: a deterministic function, or an AI task through its model route."""
    if not is_ai_task(spec["work"]):
        return WORK_FUNCTIONS[spec["work"]](context)
    stage = stage_rows(db, execution.id)[stage_key]
    return providers.run_task(
        db,
        settings,
        transport=transport,
        organization_id=execution.organization_id,
        project_id=execution.project_id,
        stage_execution_id=stage.id,
        route_key=spec["model_route"],
        task=AI_TASKS[spec["work"]],
        project_name=context.project_name,
        project_type=context.project_type,
        description=context.project_description,
        feedback=context.feedback,
    )


def _work_and_validate(
    db: Session,
    *,
    execution: WorkflowExecution,
    stage_key: str,
    spec: dict[str, Any],
    context: WorkContext,
    settings: Settings,
    transport: Any = None,
) -> StageExecution:
    """RUNNING -> work -> AI_COMPLETED (new artifact version) -> VALIDATING -> review gate.

    Every step is a transition with commit=False; the caller commits once.
    """
    try:
        output = _produce(db, execution=execution, stage_key=stage_key, spec=spec, context=context,
                          settings=settings, transport=transport)
    except providers.ProviderRunFailed as exc:
        return transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.FAILED,
                                actor=ActorType.SYSTEM, reason=f"provider failed: {exc.kind}", commit=False)
    except Exception as exc:  # noqa: BLE001 - any work failure must be recorded as FAILED, not hidden
        return transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.FAILED,
                                actor=ActorType.SYSTEM, reason=f"work failed: {type(exc).__name__}", commit=False)

    transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.AI_COMPLETED,
                     actor=ActorType.SYSTEM, output=output, commit=False)
    transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.VALIDATING,
                     actor=ActorType.SYSTEM, commit=False)
    missing = [k for k in spec["output_required_keys"] if k not in output]
    if missing:
        return transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.BLOCKED,
                                actor=ActorType.SYSTEM, reason=f"output missing keys: {', '.join(missing)}",
                                commit=False)
    return transition_stage(db, execution_id=execution.id, stage_key=stage_key,
                            to_status=StageStatus.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM, commit=False)


def _stage_and_spec(
    db: Session, execution_id: uuid.UUID, stage_key: str
) -> tuple[WorkflowExecution, StageExecution, dict[str, Any], Project]:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise not_found()
    stage = stage_rows(db, execution_id).get(stage_key)
    if stage is None:
        raise AppError(404, "unknown_stage", "Stage does not exist in this workflow")
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    return execution, stage, stage_spec(version, stage_key), db.get(Project, execution.project_id)


def run_deterministic_stage(db: Session, *, execution_id: uuid.UUID, stage_key: str,
                            settings: Settings | None = None, transport: Any = None) -> StageExecution:
    """First run of a stage. No AI: the stage's registered function produces the output.

    The stage ends in AWAITING_HUMAN_REVIEW. Approval, rework and downstream start are separate.
    """
    try:
        execution, stage, spec, project = _stage_and_spec(db, execution_id, stage_key)
        if stage.status == StageStatus.READY.value and not dependencies_satisfied(db, execution, stage_key):
            raise AppError(409, "dependencies_not_satisfied", "Upstream stages must be approved first")
        if stage.status != StageStatus.READY.value:
            raise AppError(409, "invalid_transition", "Only a READY stage can run")
        transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                         to_status=StageStatus.RUNNING, actor=ActorType.SYSTEM, commit=False)
        context = WorkContext(project_name=project.name, project_description=project.description,
                              project_type=project.project_type, revision=1)
        result = _work_and_validate(db, execution=execution, stage_key=stage_key, spec=spec, context=context,
                                    settings=settings or get_settings(), transport=transport)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def run_rework(db: Session, *, execution_id: uuid.UUID, stage_key: str,
               settings: Settings | None = None, transport: Any = None) -> StageExecution:
    """Answer open change requests with a new artifact version. The loop is bounded."""
    try:
        execution, stage, spec, project = _stage_and_spec(db, execution_id, stage_key)
        if stage.status != StageStatus.CHANGES_REQUESTED.value:
            raise AppError(409, "invalid_transition", "Rework runs only after changes were requested")
        if stage.rework_count >= MAX_REWORK_LOOPS:
            raise AppError(409, "rework_limit_reached", f"Rework is limited to {MAX_REWORK_LOOPS} loops")

        open_requests = list(
            db.execute(
                select(ChangeRequest)
                .where(ChangeRequest.stage_execution_id == stage.id, ChangeRequest.status == "open")
                .order_by(ChangeRequest.created_at)
            ).scalars()
        )
        transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=StageStatus.RUNNING,
                         actor=ActorType.SYSTEM, commit=False)
        stage.rework_count += 1
        context = WorkContext(
            project_name=project.name,
            project_description=project.description,
            project_type=project.project_type,
            revision=stage.rework_count + 1,
            feedback=tuple(cr.comment for cr in open_requests),
        )
        result = _work_and_validate(db, execution=execution, stage_key=stage_key, spec=spec, context=context,
                                    settings=settings or get_settings(), transport=transport)
        if result.status == StageStatus.AWAITING_HUMAN_REVIEW.value:
            _, version = artifacts.current_version(db, stage.id)
            now = datetime.now(UTC)
            for cr in open_requests:
                cr.status = "resolved"
                cr.resulting_artifact_version_id = version.id
                cr.resolved_at = now
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def execution_view(db: Session, user: User, execution_id: uuid.UUID) -> dict[str, Any]:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None or project_role(db, user, execution.project_id) is None:
        raise not_found()
    stages = stage_rows(db, execution.id)
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    return {
        "id": str(execution.id),
        "project_id": str(execution.project_id),
        "status": execution.status,
        "workflow": {"key": version.spec_json["key"], "name": version.spec_json["name"]},
        "stages": [
            {
                "key": spec["id"],
                "name": spec["name"],
                "status": stages[spec["id"]].status,
                "version": stages[spec["id"]].version,
            }
            for spec in version.spec_json["stages"]
        ],
    }
