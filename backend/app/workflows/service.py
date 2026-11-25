"""Workflow engine service. The only writer of stage state.

Concurrency: every transition locks its workflow execution row first, then the stage row, so
transitions within one execution are serialized. Optional expected_version gives callers an
optimistic check on top of the lock.

Atomicity: callers that combine several transitions (an approval, a rework run) pass commit=False
and commit once at the end. Any error rolls the whole unit back.
"""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import sandbox_client
from app.activity import service as activity
from app.agents import runner as agent_runner
from app.agents import service as agent_service
from app.agents.models import ReviewRecord
from app.approvals.models import ChangeRequest
from app.artifacts import service as artifacts
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.config import Settings, get_settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks import service as hooks
from app.jobs import service as jobs
from app.organizations.models import MemberProfile
from app.projects.models import Project, ProjectMember
from app.providers import service as providers
from app.providers.models import AgentRun
from app.providers.tasks import AI_TASKS, is_ai_task
from app.rules import service as rule_service
from app.sensors import service as sensors
from app.sensors.models import SensorEvidence
from app.workflows import conditions
from app.workflows.compiler import CompiledWorkflow, compile_workflow
from app.workflows.models import (
    StageDependency,
    StageEscalation,
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
_NOTIFY_ONLY_EVENTS = {
    StageStatus.AWAITING_USER_INPUT: "stage.awaiting_user_input",
    StageStatus.FAILED: "stage.failed",
    StageStatus.CHANGES_REQUESTED: "stage.changes_requested",
    StageStatus.REJECTED: "stage.rejected",
}


def publish_version(db: Session, raw: dict[str, Any]) -> WorkflowVersion:
    """Compile and store a new platform version. Nothing is stored if compilation fails."""
    compiled: CompiledWorkflow = compile_workflow(raw, known_work=set(KNOWN_WORK))
    version = store_version(db, compiled)
    db.commit()
    return version


def store_version(db: Session, compiled: CompiledWorkflow, *, organization_id: uuid.UUID | None = None,
                  published_by: uuid.UUID | None = None) -> WorkflowVersion:
    """Adds the next immutable version. The caller commits."""
    key = compiled.spec["key"]
    owner = WorkflowDefinition.organization_id.is_(None) if organization_id is None \
        else WorkflowDefinition.organization_id == organization_id
    definition = db.execute(select(WorkflowDefinition).where(owner, WorkflowDefinition.key == key)).scalar_one_or_none()
    if definition is None:
        definition = WorkflowDefinition(id=uuid7(), organization_id=organization_id, key=key,
                                        name=compiled.spec["name"])
        db.add(definition)
        db.flush()
    definition.name = compiled.spec["name"]
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
        published_by=published_by,
    )
    db.add(version)
    db.flush()
    return version


def held_profiles(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> list[str]:
    return list(db.execute(select(MemberProfile.profile_key).where(
        MemberProfile.organization_id == organization_id, MemberProfile.user_id == user_id)).scalars())


def approval_roles(db: Session, user: User, project: Project, role: str) -> list[str]:
    """The project role plus one entry per professional profile this person was confirmed for."""
    return [role, *(f"profile:{key}" for key in held_profiles(db, user.id, project.organization_id))]


def project_role(db: Session, user: User, project_id: uuid.UUID) -> str | None:
    return db.execute(
        select(ProjectMember.project_role).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user.id
        )
    ).scalar_one_or_none()


def stage_spec_from(spec: dict[str, Any], stage_key: str) -> dict[str, Any]:
    return next((s for s in spec["stages"] if s["id"] == stage_key), {})


def _compact(content: Any) -> str:
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _work_context(db: Session, execution: WorkflowExecution, project: Project, spec: dict[str, Any], revision: int,
                  feedback: tuple[str, ...] = (), budget: int | None = None) -> WorkContext:
    """What this run may draw on: the confirmed brief and approved earlier work, within a size budget.

    The stage's own `reads` list comes first, most important first; the nearest earlier work fills what is left.
    The budget is shared fairly, so one long deliverable cannot push out the others, and every cut is recorded.
    """
    budget = budget if budget is not None else get_settings().context_budget_chars
    stages = stage_rows(db, execution.id)
    specs = {s["id"]: s for s in db.get(WorkflowVersion, execution.workflow_version_id).spec_json["stages"]}
    nearest: list[str] = []
    frontier, seen = list(spec["depends_on"]), set()
    while frontier:
        key = frontier.pop(0)
        if key in seen:
            continue
        seen.add(key)
        nearest.append(key)
        frontier.extend(specs[key]["depends_on"])
    wanted = list(dict.fromkeys([*spec.get("reads", []), *nearest]))
    chosen: list[tuple[str, str, str, str]] = []  # (stage, reason, full text, version id)
    for key in wanted:
        current = artifacts.current_version(db, stages[key].id) if key in stages else None
        if current is not None and stages[key].status == StageStatus.APPROVED.value:
            reason = "needed by this step" if key in spec.get("reads", []) else "nearest earlier work"
            chosen.append((key, reason, _compact(current[1].content_json), str(current[1].id)))
        if len(chosen) >= 8:
            break
    upstream: list[str] = []
    info: list[dict[str, Any]] = []
    left = budget
    for index, (key, reason, text, version_id) in enumerate(chosen):
        share = max(0, left // (len(chosen) - index))
        part = text if len(text) <= share else text[:max(0, share - 12)] + "…(cut)"
        if share < 200:  # too little room to be useful
            info.append({"stage": key, "name": specs[key]["name"], "reason": reason, "chars": 0,
                         "full_chars": len(text), "included": False})
            continue
        upstream.append(f"{specs[key]['name']}: {part}")
        info.append({"stage": key, "name": specs[key]["name"], "reason": reason, "chars": len(part),
                     "full_chars": len(text), "included": True, "version_id": version_id})
        left -= len(part)
    return WorkContext(project_name=project.name, project_description=project.description,
                       project_type=project.project_type, revision=revision, feedback=feedback,
                       intake=tuple(execution.config_snapshot.get("intake", [])), upstream=tuple(upstream),
                       upstream_info=tuple(info))


def stage_spec(version: WorkflowVersion, stage_key: str) -> dict[str, Any]:
    spec = next((s for s in version.spec_json["stages"] if s["id"] == stage_key), None)
    if spec is None:
        raise AppError(404, "unknown_stage", "Stage does not exist in this workflow")
    return spec


def start_execution(db: Session, user: User, *, project_id: uuid.UUID, workflow_version_id: uuid.UUID,
                    intake: list[str] | None = None, facts: dict[str, Any] | None = None,
                    as_project_manager: bool = False) -> WorkflowExecution:
    project = db.get(Project, project_id)
    if as_project_manager:  # P4: the project's PM starts delivery from the approved brief
        if project is None or project.project_manager_id != user.id:
            raise AppError(403, "not_permitted", "Only the project's Project Manager can start delivery")
    else:
        role = project_role(db, user, project_id)
        if role is None:
            raise not_found()
        if role != "project_owner":
            raise AppError(403, "not_permitted", "Only the project owner can start a workflow")

    version = db.get(WorkflowVersion, workflow_version_id)
    owner = db.get(WorkflowDefinition, version.definition_id).organization_id if version else None
    if version is None or owner not in (None, project.organization_id):
        raise AppError(404, "unknown_workflow_version", "Workflow version does not exist")
    compiled = compile_workflow(version.spec_json, known_work=set(KNOWN_WORK))

    agent_keys = {k for s in version.spec_json["stages"]
                  for k in (s.get("agent"), s.get("reviewer"), *s.get("specialists", [])) if k}
    execution = WorkflowExecution(
        id=uuid7(),
        project_id=project.id,
        workflow_version_id=version.id,
        organization_id=project.organization_id,
        status="RUNNING",
        created_by=user.id,
        config_snapshot={
            "agent_versions": agent_service.snapshot_versions(db, project.organization_id, agent_keys),
            **rule_service.snapshot(db, project.organization_id, project.id),
            "intake": intake or [],
            "facts": facts or {},  # what stage conditions may test; fixed when delivery starts
        },
    )
    db.add(execution)
    db.flush()
    for stage_id, needs in compiled.graph.items():
        for dep in needs:
            db.add(StageDependency(workflow_execution_id=execution.id, stage_key=stage_id, depends_on=dep))
    conditional = {st["id"] for st in version.spec_json["stages"] if st.get("condition")}
    for stage_id in compiled.order:
        root = not compiled.graph[stage_id] and stage_id not in conditional  # conditional roots are decided below
        status = StageStatus.READY if root else StageStatus.NOT_STARTED
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
    hooks.run_hooks(db, hook_scope(db, execution), "workflow.started")
    if conditional:
        refresh_readiness(db, execution)
    db.commit()
    return execution


def hook_scope(db: Session, execution: WorkflowExecution, stage_key: str | None = None) -> hooks.HookScope:
    project = db.get(Project, execution.project_id)
    profile = None
    if stage_key:
        profile = stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key).get("profile")
    return hooks.HookScope(organization_id=execution.organization_id, project_id=execution.project_id,
                           project_type=project.project_type, execution_id=execution.id, stage_key=stage_key,
                           profile=profile)


def lock_stage(db: Session, execution_id: uuid.UUID, stage_key: str) -> tuple[WorkflowExecution, StageExecution]:
    # populate_existing: the locked read must replace anything this session remembers from before the lock
    execution = db.execute(
        select(WorkflowExecution).where(WorkflowExecution.id == execution_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if execution is None:
        raise not_found()
    stage = db.execute(
        select(StageExecution)
        .where(StageExecution.workflow_execution_id == execution_id, StageExecution.stage_key == stage_key)
        .with_for_update().execution_options(populate_existing=True)
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
    stage.updated_at = datetime.now(UTC)  # the recovery sweep measures how long a stage has waited from this
    if output is not None:
        stage.output_json = output
    if to_status is StageStatus.AI_COMPLETED and output is not None:
        created = artifacts.create_version(
            db,
            project_id=execution.project_id,
            stage_execution_id=stage.id,
            kind=stage_key,
            content=output,
        )
        event = "artifact.created" if created.version_number == 1 else "artifact.versioned"
        hooks.run_hooks(db, hook_scope(db, execution, stage_key), event)
    stage.failure_reason = reason[:300] if to_status in (StageStatus.FAILED, StageStatus.BLOCKED) else None
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
    if to_status in _NOTIFY_ONLY_EVENTS:
        hooks.run_hooks(db, hook_scope(db, execution, stage_key), _NOTIFY_ONLY_EVENTS[to_status])
    if commit:
        db.commit()
    return stage


def stage_rows(db: Session, execution_id: uuid.UUID, *, fresh: bool = False) -> dict[str, StageExecution]:
    """All stages of an execution. fresh=True re-reads them from the database (pending changes are flushed first),
    which matters when another worker may have moved a parallel branch since this session last looked."""
    query = select(StageExecution).where(StageExecution.workflow_execution_id == execution_id)
    if fresh:
        db.flush()
        query = query.execution_options(populate_existing=True)
    return {s.stage_key: s for s in db.execute(query).scalars()}


def dependencies_satisfied(db: Session, execution: WorkflowExecution, stage_key: str) -> bool:
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    stages = stage_rows(db, execution.id)
    return all(
        StageStatus(stages[d].status) in SATISFIES_DEPENDENCY
        for d in stage_spec(version, stage_key)["depends_on"]
    )


def refresh_readiness(db: Session, execution: WorkflowExecution) -> None:
    """NOT_STARTED -> READY when every dependency is satisfied; NOT_STARTED -> SKIPPED when the stage's condition
    is false. Runs under the execution's row lock, so two branches finishing at once cannot both miss the join."""
    version = db.get(WorkflowVersion, execution.workflow_version_id)
    stages = stage_rows(db, execution.id, fresh=True)
    needs: dict[str, list[str]] = {}
    for row in db.execute(select(StageDependency).where(StageDependency.workflow_execution_id == execution.id)):
        needs.setdefault(row[0].stage_key, []).append(row[0].depends_on)
    project = db.get(Project, execution.project_id)
    facts = {"project_type": project.project_type, **execution.config_snapshot.get("facts", {})}

    def artifact_field(stage_key: str, field: str) -> tuple[bool, Any]:
        row = stages.get(stage_key)
        current = artifacts.current_version(db, row.id) if row is not None else None
        if current is None or StageStatus(row.status) not in (StageStatus.APPROVED, StageStatus.COMPLETED):
            return False, None
        content = current[1].content_json
        return field in content, content.get(field)

    for spec in version.spec_json["stages"]:
        stage = stages[spec["id"]]
        if stage.status != StageStatus.NOT_STARTED.value:
            continue
        deps = needs.get(spec["id"], spec["depends_on"])
        if not all(StageStatus(stages[d].status) in SATISFIES_DEPENDENCY for d in deps):
            continue
        target, reason = StageStatus.READY, "dependencies satisfied"
        if spec.get("condition"):
            met, why = conditions.evaluate(spec["condition"], facts, artifact_field)
            if not met:
                target, reason = StageStatus.SKIPPED, f"condition not met: {why}"
        stage.status = target.value
        stage.version += 1
        stage.updated_at = datetime.now(UTC)
        db.add(StageTransition(stage_execution_id=stage.id, from_status=StageStatus.NOT_STARTED.value,
                               to_status=target.value, actor_type=ActorType.SYSTEM.value, reason=reason[:300]))
        append_event(
            db,
            chain_key=org_chain(execution.organization_id),
            event_type=f"stage.{target.value.lower()}",
            actor_type=ActorType.SYSTEM.value,
            organization_id=execution.organization_id,
            project_id=execution.project_id,
            payload={"workflow_execution": execution.id.hex, "stage": spec["id"], "reason": reason[:200]},
        )
        if target is StageStatus.SKIPPED:
            hooks.run_hooks(db, hook_scope(db, execution, spec["id"]), "stage.skipped")


def _produce(
    db: Session,
    *,
    execution: WorkflowExecution,
    stage_key: str,
    spec: dict[str, Any],
    context: WorkContext,
    settings: Settings,
    transport: Any,
    lead_sink: list[uuid.UUID],
) -> dict[str, Any]:
    """Run the stage's work: a deterministic function, a lead agent, or an AI task through its model route."""
    if not is_ai_task(spec["work"]):
        return WORK_FUNCTIONS[spec["work"]](context)
    stage = stage_rows(db, execution.id)[stage_key]
    scope = hook_scope(db, execution, stage_key)
    hooks.run_hooks(db, scope, "agent.started")
    try:
        output = _run_ai(db, execution=execution, stage=stage, spec=spec, context=context, settings=settings,
                         transport=transport, lead_sink=lead_sink)
    except Exception:
        hooks.run_hooks(db, scope, "agent.failed")
        raise
    hooks.run_hooks(db, scope, "agent.completed")
    return output


def _run_ai(
    db: Session,
    *,
    execution: WorkflowExecution,
    stage: StageExecution,
    spec: dict[str, Any],
    context: WorkContext,
    settings: Settings,
    transport: Any,
    lead_sink: list[uuid.UUID],
) -> dict[str, Any]:
    stage_key = stage.stage_key
    config = execution.config_snapshot
    if spec.get("agent") and spec.get("specialists"):
        notes = []
        for key in spec["specialists"]:  # each is its own recorded execution; the orchestrator routes, agents never
            contribution = agent_runner.run_specialist(  # call each other (RD-9)
                db, settings, transport=transport, organization_id=execution.organization_id,
                project_id=execution.project_id, stage_execution_id=stage.id, stage_key=stage_key, agent_key=key,
                profile_key=spec.get("profile"), context=context, config=config)
            notes.append(f"{key}: {json.dumps(contribution, sort_keys=True)[:1500]}")
        context = replace(context, contributions=tuple(notes))
    if spec.get("agent"):
        return agent_runner.run_lead(
            db, settings, transport=transport, organization_id=execution.organization_id,
            project_id=execution.project_id, stage_execution_id=stage.id, stage_key=stage_key,
            agent_key=spec["agent"],
            profile_key=spec.get("profile"), context=context, sink=lead_sink, config=config,
            accept=_record_acceptance(spec),
        )
    rules = rule_service.resolve(db, config, project_id=execution.project_id, profile=spec.get("profile"),
                                 stage=stage_key, agent=None)
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
        rules_text=rule_service.render(rules),
        rule_refs=rule_service.references(rules),
    )


def _record_acceptance(spec: dict[str, Any]) -> Any:
    if not spec.get("records_min"):
        return None
    from app.work.bridge import acceptance

    return acceptance(spec)


class Superseded(Exception):
    """This run no longer owns the stage (it was recovered or changed meanwhile). Its result is discarded."""


def _locked(db: Session, execution_id: uuid.UUID, stage_key: str, status: StageStatus,
            version: int) -> tuple[WorkflowExecution, StageExecution]:
    """Takes the row locks for a short step, but only if the stage is still exactly where this run left it."""
    execution, stage = lock_stage(db, execution_id, stage_key)
    if stage.status != status.value or stage.version != version:
        raise Superseded(f"{stage_key} is {stage.status} v{stage.version}, expected {status.value} v{version}")
    return execution, stage


def open_escalation(db: Session, stage: StageExecution) -> StageEscalation | None:
    return db.execute(select(StageEscalation).where(StageEscalation.stage_execution_id == stage.id,
                                                    StageEscalation.status == "open")).scalars().first()


def _not_escalated(db: Session, stage: StageExecution) -> None:
    if open_escalation(db, stage) is not None:
        raise AppError(409, "escalated", "This step is paused by an escalation until a professional resolves it")


def _finish_run(db: Session, *, execution_id: uuid.UUID, stage_key: str, spec: dict[str, Any],
                context: WorkContext, settings: Settings, transport: Any, running_version: int,
                open_request_ids: tuple[uuid.UUID, ...] = ()) -> StageExecution:
    """Runs the stage's work with no lock held, then records the result in one short locked step."""
    execution = db.get(WorkflowExecution, execution_id)
    lead_sink: list[uuid.UUID] = []
    failure: str | None = None
    output: dict[str, Any] = {}
    try:
        output = _produce(db, execution=execution, stage_key=stage_key, spec=spec, context=context,
                          settings=settings, transport=transport, lead_sink=lead_sink)
    except agent_runner.AgentRefused as exc:
        failure = f"agent refused: {exc}"
    except providers.ProviderRunFailed as exc:
        failure = f"provider failed: {exc.kind}"
    except Exception as exc:  # noqa: BLE001 - any work failure must be recorded as FAILED, not hidden
        db.rollback()  # the session may be unusable; the failure itself is recorded below
        failure = f"work failed: {type(exc).__name__}"

    execution, stage = _locked(db, execution_id, stage_key, StageStatus.RUNNING, running_version)
    if failure is not None:
        stage.run_job_id = None
        result = transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=StageStatus.FAILED,
                                  actor=ActorType.SYSTEM, reason=failure[:300], commit=False)
        _note_result(spec, result)
        db.commit()
        return result
    if spec.get("assemble"):  # BRD and SRS drafts from the approved records become part of what is reviewed
        from app.work import documents

        output = {**output, "documents": documents.assemble(
            db, project=db.get(Project, execution.project_id), stage_execution_id=stage.id,
            execution_id=execution.id, doc_types=list(spec["assemble"]))}
    transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=StageStatus.AI_COMPLETED,
                     actor=ActorType.SYSTEM, output=output, commit=False)
    if lead_sink:
        _, produced = artifacts.current_version(db, stage.id)
        for run in db.execute(select(AgentRun).where(AgentRun.id.in_(lead_sink))).scalars():
            run.output_artifact_version_id = produced.id
    if spec.get("records"):
        from app.work import bridge

        _, produced = artifacts.current_version(db, stage.id)
        bridge.propose_from_output(db, project=db.get(Project, execution.project_id), stage_execution_id=stage.id,
                                   stage_key=stage_key, spec=spec, output=output, artifact_version_id=produced.id)
    failures, _ = hooks.run_hooks(db, hook_scope(db, execution, stage_key), "stage.ai_completed")
    transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=StageStatus.VALIDATING,
                     actor=ActorType.SYSTEM, commit=False)
    stop: str | None = None
    if failures:
        stop = f"hook: {'; '.join(failures)}"
    else:
        _, version = artifacts.current_version(db, stage.id)
        missing = [k for k in spec["output_required_keys"] if k not in version.content_json]
        if missing:
            stop = f"output missing keys: {', '.join(missing)}"
        else:
            pre, _ = hooks.run_hooks(db, hook_scope(db, execution, stage_key), "stage.validation_started", "pre")
            if pre:
                stop = f"hook: {'; '.join(pre)}"
            else:
                hooks.run_hooks(db, hook_scope(db, execution, stage_key), "stage.validation_started")
    if stop:
        stage.run_job_id = None
        result = _block(db, execution, stage_key, stop)
        _note_result(spec, result)
        db.commit()
        return result
    validating_version = stage.version
    db.commit()
    return _validate(db, execution_id=execution_id, stage_key=stage_key, spec=spec, settings=settings,
                     transport=transport, validating_version=validating_version, lead_run_ids=lead_sink,
                     open_request_ids=open_request_ids)


def _validate(db: Session, *, execution_id: uuid.UUID, stage_key: str, spec: dict[str, Any], settings: Settings,
              transport: Any, validating_version: int, lead_run_ids: list[uuid.UUID],
              open_request_ids: tuple[uuid.UUID, ...] = ()) -> StageExecution:
    """VALIDATING to the gate. Builds, tests, sensors and the AI review run with no lock held; deterministic checks
    come before any review. The final transition is one short locked step. Safe to run again after a crash."""
    execution = db.get(WorkflowExecution, execution_id)
    stage = stage_rows(db, execution_id)[stage_key]
    _, version = artifacts.current_version(db, stage.id)
    _verify_in_sandbox(db, execution, stage, spec, version, settings)
    sensors.run_stage_sensors(db, execution, stage, spec, version)
    blocked = sensors.blocking(db, stage, spec, version)
    review_failure = None
    if not blocked and spec.get("reviewer"):
        review_failure = _run_review(db, execution=execution, stage_key=stage_key, spec=spec, settings=settings,
                                     transport=transport, lead_run_ids=lead_run_ids)
    db.commit()  # the evidence and the review are kept even if the gate below finds the stage changed

    execution, stage = _locked(db, execution_id, stage_key, StageStatus.VALIDATING, validating_version)
    scope = hook_scope(db, execution, stage_key)
    stage.run_job_id = None
    if blocked:
        result = _block(db, execution, stage_key, f"mandatory sensors not satisfied: {', '.join(blocked)}")
    else:
        failures, _ = hooks.run_hooks(db, scope, "stage.validation_completed")
        if failures:
            result = _block(db, execution, stage_key, f"hook: {'; '.join(failures)}")
        elif review_failure is not None:
            result = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                      to_status=StageStatus.FAILED, actor=ActorType.SYSTEM,
                                      reason=review_failure[:300], commit=False)
        elif not spec.get("human_gate", True):
            result = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                      to_status=StageStatus.COMPLETED, actor=ActorType.SYSTEM,
                                      reason="validated; no human gate configured", commit=False)
        else:
            pre, _ = hooks.run_hooks(db, scope, "stage.approval_requested", "pre")
            if pre:
                result = _block(db, execution, stage_key, f"hook: {'; '.join(pre)}")
            else:
                result = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                          to_status=StageStatus.AWAITING_HUMAN_REVIEW, actor=ActorType.SYSTEM,
                                          commit=False)
                hooks.run_hooks(db, scope, "stage.approval_requested")
    if result.status == StageStatus.AWAITING_HUMAN_REVIEW.value and open_request_ids:
        _, current = artifacts.current_version(db, stage.id)
        now = datetime.now(UTC)
        for cr in db.execute(select(ChangeRequest).where(ChangeRequest.id.in_(open_request_ids),
                                                         ChangeRequest.status == "open")).scalars():
            cr.status, cr.resulting_artifact_version_id, cr.resolved_at = "resolved", current.id, now
    _note_result(spec, result)
    db.commit()
    return result


_RESULT_TITLES = {
    StageStatus.AWAITING_HUMAN_REVIEW.value: "{name} is ready and waiting for a professional's approval",
    StageStatus.COMPLETED.value: "{name} is done (no approval needed)",
    StageStatus.BLOCKED.value: "{name} is blocked",
    StageStatus.FAILED.value: "{name} stopped",
}


def _note_result(spec: dict[str, Any], stage: StageExecution) -> None:
    title = _RESULT_TITLES.get(stage.status, "{name}: " + stage.status.lower())
    activity.note("result", title.format(name=spec["name"]),
                  {"status": stage.status, "reason": stage.failure_reason} if stage.failure_reason else
                  {"status": stage.status})


def _block(db: Session, execution: WorkflowExecution, stage_key: str, reason: str) -> StageExecution:
    return transition_stage(db, execution_id=execution.id, stage_key=stage_key, to_status=StageStatus.BLOCKED,
                            actor=ActorType.SYSTEM, reason=reason[:300], commit=False)


def _verify_in_sandbox(db: Session, execution: WorkflowExecution, stage: StageExecution, spec: dict[str, Any],
                       version: Any, settings: Settings) -> None:
    """Builds and tests the generated files for real. Without a result, no evidence exists and the gate stays shut."""
    if not spec.get("sandbox"):
        return
    if db.execute(select(SensorEvidence.id).where(SensorEvidence.artifact_version_id == version.id,
                                                  SensorEvidence.source == "sandbox")).first():
        return  # this exact version was already built and tested
    source = version
    if spec.get("sandbox_source"):
        upstream = artifacts.current_version(db, stage_rows(db, execution.id)[spec["sandbox_source"]].id)
        if upstream is None:
            return
        source = upstream[1]
    try:
        result = sandbox_client.sandbox_for(settings).run(sandbox_client.project_files(source.content_json))
    except (sandbox_client.SandboxUnavailable, OSError, ValueError):
        result = {"status": "unavailable"}
    outcome: dict[str, bool] = {}
    checks_seen: list[dict[str, Any]] = []
    if result.get("status") == "completed":
        for kind, name in (("build", "build"), ("unit_tests", "unit_tests")):
            check = result["checks"][name]
            outcome[kind] = bool(check["passed"])
            lines = [line[:500] for line in str(check.get("output", "")).splitlines() if line.strip()][-20:]
            checks_seen.append({"name": "Build" if kind == "build" else "Tests", "passed": bool(check["passed"]),
                                "summary": str(check["summary"])[:500], "output": lines[-8:]})
            db.add(SensorEvidence(organization_id=execution.organization_id, project_id=execution.project_id,
                                  artifact_version_id=version.id, kind=kind, source="sandbox",
                                  outcome="pass" if check["passed"] else "fail", summary=str(check["summary"])[:500],
                                  findings=[] if check["passed"] else [str(check["summary"])[:500], *lines]))
        db.flush()
    if checks_seen:
        verdict = ", ".join(f"{c['name'].lower()} {'passed' if c['passed'] else 'failed'}" for c in checks_seen)
        activity.note("checks", f"Built and tested the generated code in the sandbox: {verdict}",
                      {"checks": checks_seen, "files": activity.files_of(source.content_json.get("source_files"))})
    else:
        activity.note("checks", "The sandbox could not run the code, so no build or test result exists yet",
                      {"status": result.get("status")})
    append_event(db, chain_key=org_chain(execution.organization_id), event_type="sandbox.completed",
                 actor_type=ActorType.SYSTEM.value, organization_id=execution.organization_id,
                 project_id=execution.project_id,
                 payload={"stage": stage.stage_key, "artifact_version": str(version.id),
                          "status": result.get("status"), "language": result.get("language"), "passed": outcome})


def _run_review(
    db: Session, *, execution: WorkflowExecution, stage_key: str, spec: dict[str, Any], settings: Settings,
    transport: Any, lead_run_ids: list[uuid.UUID],
) -> str | None:
    """The independent AI reviewer checks the current version. Returns why the stage must stop, or None."""
    stage = stage_rows(db, execution.id)[stage_key]
    _, version = artifacts.current_version(db, stage.id)
    if db.execute(select(ReviewRecord.id).where(ReviewRecord.stage_execution_id == stage.id,
                                                ReviewRecord.artifact_version_id == version.id)).first():
        return None  # this exact version was already reviewed
    lead_run = lead_run_ids[0] if lead_run_ids else db.execute(
        select(AgentRun.id).where(AgentRun.stage_execution_id == stage.id, AgentRun.kind == "lead",
                                  AgentRun.status == "succeeded").order_by(AgentRun.id.desc())
    ).scalars().first()
    try:
        agent_runner.run_reviewer(
            db, settings, transport=transport, organization_id=execution.organization_id,
            project_id=execution.project_id, stage_execution_id=stage.id, stage_key=stage_key,
            reviewer_key=spec["reviewer"], lead_key=spec["agent"], artifact_version_id=version.id,
            content=version.content_json, lead_run_id=lead_run or uuid.UUID(int=0), profile_key=spec.get("profile"),
            config=execution.config_snapshot,
        )
    except agent_runner.AgentRefused as exc:
        return f"review refused: {exc}"
    except providers.ProviderRunFailed as exc:
        return f"review failed: {exc.kind}"
    return None


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
    """First run of a stage: claim it (READY -> RUNNING, committed), do the work, validate, stop at the gate.

    No lock is held while the AI or the sandbox works, so other stages and approvals are never kept waiting.
    """
    try:
        execution, stage, spec, project = _stage_and_spec(db, execution_id, stage_key)
        if stage.status == StageStatus.READY.value and not dependencies_satisfied(db, execution, stage_key):
            raise AppError(409, "dependencies_not_satisfied", "Upstream stages must be approved first")
        if stage.status != StageStatus.READY.value:
            raise AppError(409, "invalid_transition", "Only a READY stage can run")
        _not_escalated(db, stage)
        scope = hook_scope(db, execution, stage_key)
        failures, _ = hooks.run_hooks(db, scope, "stage.started", "pre")
        if failures:
            result = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                      to_status=StageStatus.BLOCKED, actor=ActorType.SYSTEM,
                                      reason=f"hook: {'; '.join(failures)}", commit=False)
            db.commit()
            return result
        running = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                   to_status=StageStatus.RUNNING, actor=ActorType.SYSTEM, commit=False)
        running.run_job_id = jobs.current_job_id()
        hooks.run_hooks(db, scope, "stage.started")
        context = _work_context(db, execution, project, spec, 1)
        running_version = running.version
        db.commit()
    except Exception:
        db.rollback()
        raise
    with activity.scope(stage_key=stage_key, profile_key=spec.get("profile")):
        activity.note("stage", f"Started {spec['name']}")
        return _settle(db, lambda: _finish_run(
            db, execution_id=execution_id, stage_key=stage_key, spec=spec, context=context,
            settings=settings or get_settings(), transport=transport, running_version=running_version))


def _settle(db: Session, work: Any) -> StageExecution:
    try:
        return work()
    except Superseded:
        db.rollback()  # someone else now owns this stage; this run's result is not used
        raise
    except Exception:
        db.rollback()
        raise


def run_rework(db: Session, *, execution_id: uuid.UUID, stage_key: str,
               settings: Settings | None = None, transport: Any = None) -> StageExecution:
    """Answer change requests or blocking sensor findings with a new version. The loop is bounded."""
    try:
        execution, stage, spec, project = _stage_and_spec(db, execution_id, stage_key)
        if stage.status not in (StageStatus.CHANGES_REQUESTED.value, StageStatus.BLOCKED.value):
            raise AppError(409, "invalid_transition", "Rework needs requested changes or a blocked stage")
        if stage.rework_count >= MAX_REWORK_LOOPS:
            raise AppError(409, "rework_limit_reached", f"Rework is limited to {MAX_REWORK_LOOPS} loops")
        _not_escalated(db, stage)
        open_requests = list(
            db.execute(
                select(ChangeRequest)
                .where(ChangeRequest.stage_execution_id == stage.id, ChangeRequest.status == "open")
                .order_by(ChangeRequest.created_at)
            ).scalars()
        )
        sensor_feedback = sensors.blocking_feedback(db, stage, spec)
        scope = hook_scope(db, execution, stage_key)
        failures, records = hooks.run_hooks(db, scope, "stage.started", "pre")
        if failures:
            raise hooks.HookBlocked(scope, "stage.started", failures, records)
        running = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                   to_status=StageStatus.RUNNING, actor=ActorType.SYSTEM, commit=False)
        running.run_job_id = jobs.current_job_id()
        hooks.run_hooks(db, scope, "stage.started")
        stage.rework_count += 1
        context = _work_context(db, execution, project, spec, stage.rework_count + 1,
                                (*(cr.comment for cr in open_requests), *sensor_feedback))
        request_ids = tuple(cr.id for cr in open_requests)
        running_version = running.version
        revision = stage.rework_count + 1
        db.commit()
    except hooks.HookBlocked as exc:
        db.rollback()
        hooks.persist_blocked(db, exc)
        raise
    except Exception:
        db.rollback()
        raise
    with activity.scope(stage_key=stage_key, profile_key=spec.get("profile")):
        activity.note("stage", f"Reworking {spec['name']} (version {revision})",
                      {"addressing": list(context.feedback)[:10]})
        return _settle(db, lambda: _finish_run(
            db, execution_id=execution_id, stage_key=stage_key, spec=spec, context=context,
            settings=settings or get_settings(), transport=transport, running_version=running_version,
            open_request_ids=request_ids))


def recover_stage(db: Session, *, execution_id: uuid.UUID, stage_key: str, reason: str) -> StageExecution:
    """A run that stopped part-way (its worker died) goes back to where it started, to be run again.

    A first run returns to READY; an interrupted rework returns to CHANGES_REQUESTED without using up a loop.
    Only the system takes these edges; nothing is approved or skipped by a recovery.
    """
    try:
        execution, stage = lock_stage(db, execution_id, stage_key)
        if stage.status != StageStatus.RUNNING.value:
            raise AppError(409, "nothing_to_recover", "Only an interrupted run can be recovered")
        back = StageStatus.READY
        if stage.rework_count > 0:
            back = StageStatus.CHANGES_REQUESTED
            stage.rework_count -= 1
        stage.run_job_id = None
        result = transition_stage(db, execution_id=execution_id, stage_key=stage_key, to_status=back,
                                  actor=ActorType.SYSTEM, reason=f"recovered: {reason}"[:300], commit=False)
        hooks.run_hooks(db, hook_scope(db, execution, stage_key), "stage.recovered")
        spec = stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key)
        with activity.scope(stage_key=stage_key, profile_key=spec.get("profile")):
            activity.note("stage", f"{spec['name']} was interrupted and will run again", {"reason": reason})
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def resume_validation(db: Session, *, execution_id: uuid.UUID, stage_key: str, settings: Settings | None = None,
                      transport: Any = None) -> StageExecution:
    """Finishes the checks of a stage whose validation was interrupted. Builds and reviews already done are kept."""
    try:
        execution, stage = lock_stage(db, execution_id, stage_key)
        if stage.status != StageStatus.VALIDATING.value:
            raise AppError(409, "nothing_to_resume", "Only a stage being validated can be resumed")
        stage.run_job_id = jobs.current_job_id()
        spec = stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key)
        validating_version = stage.version
        db.commit()
    except Exception:
        db.rollback()
        raise
    with activity.scope(stage_key=stage_key, profile_key=spec.get("profile")):
        activity.note("stage", f"Resuming the checks of {spec['name']}")
        return _settle(db, lambda: _validate(
            db, execution_id=execution_id, stage_key=stage_key, spec=spec, settings=settings or get_settings(),
            transport=transport, validating_version=validating_version, lead_run_ids=[]))


def revalidate_stage(db: Session, user: User, *, execution_id: uuid.UUID, stage_key: str, settings: Settings,
                     transport: Any = None) -> StageExecution:
    """Run validation again for a stage at the gate or blocked by it. The caller cannot set the result."""
    try:
        execution, stage = lock_stage(db, execution_id, stage_key)
        role = project_role(db, user, execution.project_id)
        if role is None:
            raise not_found()
        if role == "viewer":
            raise AppError(403, "not_permitted", "Viewers cannot run validation")
        current = artifacts.current_version(db, stage.id)
        if current is None:
            raise AppError(409, "no_artifact", "This stage has nothing to validate yet")
        spec = stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key)
        append_event(db, chain_key=org_chain(execution.organization_id), event_type="stage.revalidation_requested",
                     actor_type="human", actor_id=str(user.id), organization_id=execution.organization_id,
                     project_id=execution.project_id, payload={"stage": stage_key})
        if stage.status == StageStatus.AWAITING_HUMAN_REVIEW.value:
            sensors.run_stage_sensors(db, execution, stage, spec, current[1])
            db.commit()
            return stage
        if stage.status != StageStatus.BLOCKED.value:
            raise AppError(409, "invalid_transition", "Only a blocked or reviewable stage can be validated")
        validating = transition_stage(db, execution_id=execution_id, stage_key=stage_key,
                                      to_status=StageStatus.VALIDATING, actor=ActorType.SYSTEM, commit=False)
        validating_version = validating.version
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _settle(db, lambda: _validate(db, execution_id=execution_id, stage_key=stage_key, spec=spec,
                                         settings=settings, transport=transport,
                                         validating_version=validating_version, lead_run_ids=[]))


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
