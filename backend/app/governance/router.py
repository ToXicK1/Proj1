"""HTTP API for sensors, evidence, risk acceptance, hooks, rules, teams, proposals and notifications."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.approvals.models import ChangeRequest
from app.artifacts import service as artifacts
from app.artifacts.models import ArtifactVersion
from app.audit.service import append_event, org_chain
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks import service as hooks
from app.hooks.models import HookDefinition, HookExecution, HookVersion
from app.notifications.models import Notification
from app.organizations.service import require_org_admin
from app.rules import service as rules
from app.rules.models import ChangeProposal, Rule, RuleVersion
from app.sensors import service as sensors
from app.sensors.models import RiskAcceptance, SensorEvidence
from app.sensors.registry import EVIDENCE_KINDS, SECURITY_EVIDENCE, SENSORS
from app.workflows import service as workflows
from app.workflows.models import WorkflowVersion

router = APIRouter(prefix="/api/v1", tags=["governance"])
StageKey = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]{0,63}$")]
MAX_RISK_DAYS = 30


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceIn(_Strict):
    artifact_version_id: uuid.UUID
    kind: str = Field(max_length=32)
    outcome: Literal["pass", "fail"]
    summary: str = Field(min_length=1, max_length=2000)
    findings: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=100)


class RiskIn(_Strict):
    artifact_version_id: uuid.UUID
    sensor: str = Field(max_length=64)
    reason: str = Field(min_length=20, max_length=2000)
    expires_in_days: int = Field(ge=1, le=MAX_RISK_DAYS)


class HookIn(_Strict):
    event: str = Field(max_length=64)
    phase: Literal["pre", "post"] = "post"
    priority: int = 100
    conditions: dict[str, Any] = Field(default_factory=dict)
    action: str = Field(max_length=32)
    action_config: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(max_length=2)
    timeout_ms: int = 1000
    max_retries: int = 0
    failure_policy: Literal["fail_closed", "advisory"] = "advisory"


class EnabledIn(_Strict):
    enabled: bool


class TeamIn(_Strict):
    key: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class RuleIn(_Strict):
    key: str = Field(min_length=2, max_length=64)
    scope_type: str = Field(max_length=16)
    scope_key: str = Field(default="", max_length=64)
    kind: str = Field(max_length=32)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    content: str = Field(min_length=1, max_length=2000)
    change_note: str = Field(default="", max_length=300)


class ProposalIn(_Strict):
    target: Literal["rule", "hook"]
    key: str = Field(min_length=2, max_length=64)
    payload: dict[str, Any]


class DecisionIn(_Strict):
    approve: bool
    note: str = Field(default="", max_length=500)


class LearnIn(_Strict):
    model_route: str = Field(min_length=2, max_length=64)


def _gate_target(db: DbSession, execution_id: uuid.UUID, stage_key: str, version_id: uuid.UUID, user_id: uuid.UUID,
                 ) -> tuple[Any, Any, dict[str, Any], ArtifactVersion, str]:
    execution, stage = workflows.lock_stage(db, execution_id, stage_key)
    role = db.execute(select(workflows.ProjectMember.project_role).where(
        workflows.ProjectMember.project_id == execution.project_id,
        workflows.ProjectMember.user_id == user_id)).scalar_one_or_none()
    if role is None:
        raise not_found()
    current = artifacts.current_version(db, stage.id)
    if current is None or current[1].id != version_id:
        raise AppError(409, "stale_version", "Use the current artifact version")
    spec = workflows.stage_spec(db.get(WorkflowVersion, execution.workflow_version_id), stage_key)
    return execution, stage, spec, current[1], role


@router.get("/sensors")
def sensor_catalog(_: CurrentCaller) -> dict:
    return {"items": [{"key": s.key, "category": s.category, "description": s.description, "version": s.version,
                       "evidence_kind": s.evidence_kind} for s in SENSORS.values()]}


@router.post("/workflow-executions/{execution_id}/stages/{stage_key}/validate")
def validate(execution_id: uuid.UUID, stage_key: StageKey, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    stage = workflows.revalidate_stage(db, caller.user, execution_id=execution_id, stage_key=stage_key,
                                       settings=request.app.state.settings,
                                       transport=request.app.state.provider_transport)
    return {"status": stage.status, "reason": stage.failure_reason}


@router.post("/workflow-executions/{execution_id}/stages/{stage_key}/evidence", status_code=201)
def record_evidence(execution_id: uuid.UUID, stage_key: StageKey, body: EvidenceIn, caller: CsrfCaller,
                    db: DbSession) -> dict:
    """Results from tools outside the platform. The owner of a project cannot vouch for their own work."""
    try:
        execution, _, _, version, role = _gate_target(db, execution_id, stage_key, body.artifact_version_id,
                                                      caller.user.id)
        if body.kind not in EVIDENCE_KINDS:
            raise AppError(422, "invalid_kind", "Unknown evidence kind")
        allowed = {"internal_reviewer"} if body.kind in SECURITY_EVIDENCE else {"internal_reviewer", "team_member"}
        if role not in allowed:
            raise AppError(403, "not_permitted", "Your project role cannot record this evidence")
        if version.author_user_id == caller.user.id:
            raise AppError(403, "separation_of_duties", "You cannot record evidence for your own artifact")
        db.add(SensorEvidence(organization_id=execution.organization_id, project_id=execution.project_id,
                              artifact_version_id=version.id, kind=body.kind, outcome=body.outcome,
                              summary=body.summary, findings=body.findings, recorded_by=caller.user.id))
        append_event(db, chain_key=org_chain(execution.organization_id), event_type="sensor.evidence_recorded",
                     actor_type="human", actor_id=str(caller.user.id), organization_id=execution.organization_id,
                     project_id=execution.project_id,
                     payload={"kind": body.kind, "outcome": body.outcome, "artifact_version": str(version.id)})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"kind": body.kind, "outcome": body.outcome}


@router.post("/workflow-executions/{execution_id}/stages/{stage_key}/risk-acceptances", status_code=201)
def accept_risk(execution_id: uuid.UUID, stage_key: StageKey, body: RiskIn, caller: CsrfCaller, db: DbSession) -> dict:
    try:
        execution, stage, spec, version, _ = _gate_target(db, execution_id, stage_key, body.artifact_version_id,
                                                          caller.user.id)
        require_org_admin(db, caller.user.id, execution.organization_id)
        sensor = next((s for s in spec.get("sensors") or [] if s["key"] == body.sensor), None)
        if sensor is None or not sensor.get("allow_risk_acceptance"):
            raise AppError(403, "risk_not_acceptable", "This stage does not allow accepting that risk")
        if body.sensor not in sensors.blocking(db, stage, spec, version):
            raise AppError(409, "not_blocking", "That sensor is not blocking this version")
        expires = datetime.now(UTC) + timedelta(days=body.expires_in_days)
        db.add(RiskAcceptance(id=uuid7(), organization_id=execution.organization_id, project_id=execution.project_id,
                              stage_execution_id=stage.id, artifact_version_id=version.id, sensor_key=body.sensor,
                              reason=body.reason, accepted_by=caller.user.id, expires_at=expires))
        append_event(db, chain_key=org_chain(execution.organization_id), event_type="sensor.risk_accepted",
                     actor_type="human", actor_id=str(caller.user.id), organization_id=execution.organization_id,
                     project_id=execution.project_id,
                     payload={"sensor": body.sensor, "stage": stage_key, "expires_at": expires.isoformat()})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"sensor": body.sensor, "expires_at": expires.isoformat()}


@router.get("/hook-events")
def hook_events(_: CurrentCaller) -> dict:
    return {"events": sorted(hooks.EVENTS), "pre_phase": sorted(hooks.PRE_EVENTS),
            "blockable": sorted([e, p] for e, p in hooks.BLOCKABLE), "actions": hooks.ACTION_PERMISSIONS}


@router.put("/orgs/{organization_id}/hooks/{key}", status_code=201)
def save_hook(organization_id: uuid.UUID, key: str, body: HookIn, caller: CsrfCaller, db: DbSession) -> dict:
    version = hooks.create_or_update(db, caller.user, organization_id=organization_id, key=key, raw=body.model_dump())
    return {"key": key, "version": version.version}


@router.post("/orgs/{organization_id}/hooks/{key}/enabled")
def enable_hook(organization_id: uuid.UUID, key: str, body: EnabledIn, caller: CsrfCaller, db: DbSession) -> dict:
    hooks.set_enabled(db, caller.user, organization_id=organization_id, key=key, enabled=body.enabled)
    return {"key": key, "enabled": body.enabled}


@router.get("/orgs/{organization_id}/hooks")
def list_hooks(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    items = []
    for hook in db.execute(select(HookDefinition).where(HookDefinition.organization_id == organization_id)
                           .order_by(HookDefinition.key)).scalars():
        v = db.execute(select(HookVersion).where(HookVersion.hook_id == hook.id)
                       .order_by(HookVersion.version.desc())).scalars().first()
        items.append({"key": hook.key, "enabled": hook.enabled, "version": v.version, "event": v.event,
                      "phase": v.phase, "action": v.action, "failure_policy": v.failure_policy})
    return {"items": items}


@router.get("/orgs/{organization_id}/hook-executions")
def list_hook_runs(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    rows = db.execute(select(HookExecution).where(HookExecution.organization_id == organization_id)
                      .order_by(HookExecution.id.desc()).limit(200)).scalars()
    return {"items": [{"event": r.event, "phase": r.phase, "stage": r.stage_key, "status": r.status,
                       "attempts": r.attempts, "detail": r.detail, "duration_ms": r.duration_ms} for r in rows]}


@router.post("/orgs/{organization_id}/teams", status_code=201)
def create_team(organization_id: uuid.UUID, body: TeamIn, caller: CsrfCaller, db: DbSession) -> dict:
    team = rules.create_team(db, caller.user, organization_id=organization_id, key=body.key, name=body.name)
    return {"key": team.key, "name": team.name}


@router.put("/orgs/{organization_id}/projects/{project_id}/teams/{team_key}")
def assign_team(organization_id: uuid.UUID, project_id: uuid.UUID, team_key: str, caller: CsrfCaller,
                db: DbSession) -> dict:
    rules.assign_team(db, caller.user, organization_id=organization_id, project_id=project_id, team_key=team_key)
    return {"project_id": str(project_id), "team": team_key}


@router.post("/orgs/{organization_id}/rules", status_code=201)
def save_rule(organization_id: uuid.UUID, body: RuleIn, caller: CsrfCaller, db: DbSession) -> dict:
    version = rules.save_rule(db, caller.user, organization_id=organization_id, key=body.key,
                              scope_type=body.scope_type, scope_key=body.scope_key, kind=body.kind, name=body.name,
                              description=body.description, content=body.content, note=body.change_note)
    return {"key": body.key, "rule_id": str(version.rule_id), "version": version.version}


@router.post("/orgs/{organization_id}/rules/{rule_id}/retire")
def retire_rule(organization_id: uuid.UUID, rule_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    rules.retire_rule(db, caller.user, organization_id=organization_id, rule_id=rule_id)
    return {"status": "retired"}


@router.get("/orgs/{organization_id}/rules")
def list_rules(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    items = []
    for rule in db.execute(select(Rule).where(Rule.organization_id == organization_id).order_by(Rule.key)).scalars():
        history = db.execute(select(RuleVersion).where(RuleVersion.rule_id == rule.id)
                             .order_by(RuleVersion.version)).scalars().all()
        items.append({"id": str(rule.id), "key": rule.key, "scope_type": rule.scope_type, "scope_key": rule.scope_key,
                      "kind": rule.kind, "status": rule.status, "version": history[-1].version,
                      "name": history[-1].name, "description": history[-1].description,
                      "content": history[-1].content,
                      "history": [{"version": v.version, "author": str(v.author_user_id), "note": v.change_note,
                                   "created_at": v.created_at.isoformat()} for v in history]})
    return {"items": items}


def _proposal_out(p: ChangeProposal) -> dict:
    return {"id": str(p.id), "target": p.target, "key": p.key, "payload": p.payload, "conflicts": p.conflicts,
            "proposer_type": p.proposer_type, "status": p.status, "decision_note": p.decision_note}


@router.post("/orgs/{organization_id}/proposals", status_code=201)
def propose(organization_id: uuid.UUID, body: ProposalIn, caller: CsrfCaller, db: DbSession) -> dict:
    needed = {"scope_type", "scope_key", "kind", "name", "content"}
    if body.target == "rule" and not needed <= set(body.payload):
        raise AppError(422, "invalid_rule", f"A rule proposal needs: {', '.join(sorted(needed))}")
    return _proposal_out(rules.propose_from_user(db, caller.user, organization_id=organization_id,
                                                 target=body.target, key=body.key, payload=body.payload))


@router.get("/orgs/{organization_id}/proposals")
def list_proposals(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    rows = db.execute(select(ChangeProposal).where(ChangeProposal.organization_id == organization_id)
                      .order_by(ChangeProposal.id.desc())).scalars()
    return {"items": [_proposal_out(p) for p in rows]}


@router.post("/orgs/{organization_id}/proposals/{proposal_id}/decision")
def decide(organization_id: uuid.UUID, proposal_id: uuid.UUID, body: DecisionIn, caller: CsrfCaller,
           db: DbSession) -> dict:
    try:
        return _proposal_out(rules.decide(db, caller.user, organization_id=organization_id, proposal_id=proposal_id,
                                          approve=body.approve, note=body.note))
    except Exception:
        db.rollback()
        raise


@router.post("/change-requests/{change_request_id}/learn")
def learn(change_request_id: uuid.UUID, body: LearnIn, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    if db.get(ChangeRequest, change_request_id) is None:
        raise not_found()
    try:
        proposal = rules.learn_from_correction(db, request.app.state.settings, caller.user,
                                               change_request_id=change_request_id, route_key=body.model_route,
                                               transport=request.app.state.provider_transport)
    except rules.providers.ProviderRunFailed as exc:
        db.rollback()
        raise AppError(502, "provider_failed", f"The model could not answer: {exc.kind}") from exc
    return {"proposal": _proposal_out(proposal) if proposal else None}


@router.get("/notifications")
def my_notifications(caller: CurrentCaller, db: DbSession) -> dict:
    rows = db.execute(select(Notification).where(Notification.user_id == caller.user.id)
                      .order_by(Notification.created_at.desc()).limit(100)).scalars()
    return {"items": [{"id": str(n.id), "project_id": str(n.project_id), "kind": n.kind, "message": n.message,
                       "read": n.read_at is not None} for n in rows]}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    row = db.get(Notification, notification_id)
    if row is None or row.user_id != caller.user.id:
        raise not_found()
    row.read_at = row.read_at or datetime.now(UTC)
    db.commit()
    return {"read": True}

