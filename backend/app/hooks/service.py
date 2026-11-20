"""Lifecycle hooks. Declarative only: a hook picks one built-in action and can never run code.

Only events the platform really emits can be subscribed to. A fail_closed hook is allowed only where
the engine can act on the failure, so "mandatory" always means the operation does not go ahead.
Hooks are written by organization admins or through a proposal a human approved.
"""

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.artifacts import service as artifacts
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks.models import HookDefinition, HookExecution, HookVersion
from app.notifications.models import Notification
from app.organizations.service import require_org_admin
from app.projects.models import ProjectMember
from app.sensors import service as sensors
from app.sensors.registry import SATISFYING, config_problems
from app.workflows.models import StageExecution, WorkflowExecution

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]{1,63}$")
EVENTS: frozenset[str] = frozenset({
    "project.created", "workflow.started", "workflow.completed",
    "stage.started", "stage.ai_completed", "stage.validation_started", "stage.validation_completed",
    "stage.approval_requested", "stage.approved", "stage.changes_requested", "stage.rejected", "stage.failed",
    "artifact.created", "artifact.versioned", "artifact.approved",
    "agent.started", "agent.completed", "agent.failed",
    "stage.escalated", "stage.escalation_resolved", "stage.recovered", "stage.skipped", "stage.awaiting_user_input",
})
PRE_EVENTS = frozenset({"stage.started", "stage.validation_started", "stage.approval_requested", "stage.approved"})
BLOCKABLE: frozenset[tuple[str, str]] = frozenset({
    ("stage.started", "pre"), ("stage.ai_completed", "post"), ("stage.validation_started", "pre"),
    ("stage.validation_completed", "post"), ("stage.approval_requested", "pre"),
    ("stage.approved", "pre"), ("stage.approved", "post"),
})
ACTION_PERMISSIONS = {"require_approval": "READ", "run_sensor": "READ", "notify": "WRITE"}
PROJECT_ROLES = ("project_owner", "internal_reviewer", "team_member", "viewer")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Conditions(_Strict):
    stages: list[str] = Field(default_factory=list, max_length=50)
    profiles: list[str] = Field(default_factory=list, max_length=20)
    project_types: list[str] = Field(default_factory=list, max_length=20)


class RequireApproval(_Strict):
    stages: list[str] = Field(min_length=1, max_length=50)


class RunSensor(_Strict):
    sensor: str
    config: dict[str, Any] = Field(default_factory=dict)


class Notify(_Strict):
    role: str
    message: str = Field(min_length=1, max_length=300)


ACTION_MODELS: dict[str, type[_Strict]] = {
    "require_approval": RequireApproval, "run_sensor": RunSensor, "notify": Notify,
}


@dataclass(frozen=True)
class HookScope:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    project_type: str
    execution_id: uuid.UUID | None = None
    stage_key: str | None = None
    profile: str | None = None


class HookBlocked(AppError):
    """A fail_closed hook refused the operation. records survive the rollback of that operation."""

    def __init__(self, scope: HookScope, event: str, failures: list[str], records: list[dict[str, Any]]) -> None:
        super().__init__(409, "hook_blocked", f"Blocked by a required check: {'; '.join(failures)}"[:300])
        self.scope = scope
        self.event = event
        self.records = records


def definition_problems(raw: dict[str, Any]) -> list[str]:
    """Everything that makes a hook definition unusable. Shared by the API and by proposals."""
    try:
        return _definition_problems(raw)
    except (TypeError, ValueError, AttributeError):
        return ["the hook definition is malformed"]


def _definition_problems(raw: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    event, phase = raw.get("event"), raw.get("phase")
    action = raw.get("action")
    policy = raw.get("failure_policy", "advisory")
    if event not in EVENTS:
        problems.append(f"event '{event}' is not emitted by the platform")
    if phase not in ("pre", "post"):
        problems.append("phase must be pre or post")
    elif phase == "pre" and event not in PRE_EVENTS:
        problems.append(f"event '{event}' has no pre phase")
    if policy not in ("fail_closed", "advisory"):
        problems.append("failure_policy must be fail_closed or advisory")
    elif policy == "fail_closed" and (event, phase) not in BLOCKABLE:
        problems.append(f"'{event}' ({phase}) cannot be blocked, so it cannot be fail_closed")
    if not 0 <= int(raw.get("priority", 100)) <= 1000:
        problems.append("priority must be 0 to 1000")
    if not 1 <= int(raw.get("timeout_ms", 1000)) <= 30000:
        problems.append("timeout_ms must be 1 to 30000")
    if not 0 <= int(raw.get("max_retries", 0)) <= 3:
        problems.append("max_retries must be 0 to 3")
    try:
        Conditions.model_validate(raw.get("conditions") or {})
    except ValidationError as exc:
        problems += [f"conditions: {e['msg']}" for e in exc.errors()]
    model = ACTION_MODELS.get(action)
    if model is None:
        return [*problems, f"action '{action}' does not exist"]
    required = ACTION_PERMISSIONS[action]
    if raw.get("permissions") != [required]:
        problems.append(f"permissions must be exactly ['{required}'] for this action")
    try:
        config = model.model_validate(raw.get("action_config") or {})
    except ValidationError as exc:
        return [*problems, *(f"action_config: {e['msg']}" for e in exc.errors())]
    if isinstance(config, RunSensor):
        problems += [f"action_config: {p}" for p in config_problems(config.sensor, config.config)]
        if not event or not str(event).startswith("stage."):
            problems.append("run_sensor needs a stage event")
    if isinstance(config, RequireApproval) and event == "project.created":
        problems.append("require_approval needs a running workflow")
    if isinstance(config, Notify) and config.role not in PROJECT_ROLES:
        problems.append(f"unknown project role '{config.role}'")
    return problems


def _write_version(db: Session, hook: HookDefinition, raw: dict[str, Any]) -> HookVersion:
    last = db.execute(select(func.max(HookVersion.version)).where(HookVersion.hook_id == hook.id)).scalar_one()
    fields = {
        "event": raw["event"], "phase": raw["phase"], "priority": int(raw.get("priority", 100)),
        "conditions": Conditions.model_validate(raw.get("conditions") or {}).model_dump(),
        "action": raw["action"], "action_config": raw.get("action_config") or {},
        "permissions": raw["permissions"], "timeout_ms": int(raw.get("timeout_ms", 1000)),
        "max_retries": int(raw.get("max_retries", 0)), "failure_policy": raw.get("failure_policy", "advisory"),
    }
    digest = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    version = HookVersion(id=uuid7(), hook_id=hook.id, version=(last or 0) + 1, sha256=digest, **fields)
    db.add(version)
    db.flush()
    return version


def save_hook(db: Session, *, organization_id: uuid.UUID, key: str, raw: dict[str, Any], actor_id: str) -> HookVersion:
    """Create the hook or add a version. Callers have already established human authority."""
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Hook key must be lowercase, letters, digits, '-' or '_'")
    problems = definition_problems(raw)
    if problems:
        raise AppError(422, "invalid_hook", "; ".join(problems)[:300])
    hook = db.execute(select(HookDefinition).where(HookDefinition.organization_id == organization_id,
                                                   HookDefinition.key == key)).scalar_one_or_none()
    if hook is None:
        hook = HookDefinition(id=uuid7(), organization_id=organization_id, key=key, enabled=True)
        db.add(hook)
        db.flush()
    version = _write_version(db, hook, raw)
    append_event(db, chain_key=org_chain(organization_id), event_type="hook.saved", actor_type="human",
                 actor_id=actor_id, organization_id=organization_id,
                 payload={"hook": key, "version": version.version, "event": version.event})
    return version


def create_or_update(db: Session, user: User, *, organization_id: uuid.UUID, key: str,
                     raw: dict[str, Any]) -> HookVersion:
    require_org_admin(db, user.id, organization_id)
    version = save_hook(db, organization_id=organization_id, key=key, raw=raw, actor_id=str(user.id))
    db.commit()
    return version


def set_enabled(db: Session, user: User, *, organization_id: uuid.UUID, key: str, enabled: bool) -> None:
    require_org_admin(db, user.id, organization_id)
    hook = db.execute(select(HookDefinition).where(HookDefinition.organization_id == organization_id,
                                                   HookDefinition.key == key)).scalar_one_or_none()
    if hook is None:
        raise not_found()
    hook.enabled = enabled
    append_event(db, chain_key=org_chain(organization_id), event_type="hook.enabled_changed", actor_type="human",
                 actor_id=str(user.id), organization_id=organization_id, payload={"hook": key, "enabled": enabled})
    db.commit()


def _active(db: Session, organization_id: uuid.UUID, event: str, phase: str) -> list[tuple[str, HookVersion]]:
    result = []
    for hook in db.execute(select(HookDefinition).where(HookDefinition.organization_id == organization_id,
                                                        HookDefinition.enabled.is_(True))).scalars():
        version = db.execute(select(HookVersion).where(HookVersion.hook_id == hook.id)
                             .order_by(HookVersion.version.desc())).scalars().first()
        if version is not None and version.event == event and version.phase == phase:
            result.append((hook.key, version))
    return sorted(result, key=lambda item: (item[1].priority, item[0]))


def _matches(version: HookVersion, scope: HookScope) -> bool:
    c = version.conditions
    return ((not c.get("stages") or scope.stage_key in c["stages"])
            and (not c.get("profiles") or scope.profile in c["profiles"])
            and (not c.get("project_types") or scope.project_type in c["project_types"]))


def _stage(db: Session, execution_id: uuid.UUID, key: str) -> StageExecution | None:
    return db.execute(select(StageExecution).where(StageExecution.workflow_execution_id == execution_id,
                                                   StageExecution.stage_key == key)).scalar_one_or_none()


def _perform(db: Session, version: HookVersion, scope: HookScope) -> str | None:
    """Run the action. Returns a failure description, or None on success."""
    cfg = version.action_config
    if version.action == "notify":
        members = db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == scope.project_id,
                                                                 ProjectMember.project_role == cfg["role"])).scalars()
        for user_id in members:
            db.add(Notification(id=uuid7(), organization_id=scope.organization_id, project_id=scope.project_id,
                                user_id=user_id, kind=version.event, message=cfg["message"]))
        return None
    if scope.execution_id is None:
        return "no workflow is running"
    execution = db.get(WorkflowExecution, scope.execution_id)
    if version.action == "require_approval":
        missing = [k for k in cfg["stages"] if not sensors._is_approved(db, _stage(db, execution.id, k))]
        return f"stages not approved: {', '.join(missing)}" if missing else None
    stage = _stage(db, execution.id, scope.stage_key) if scope.stage_key else None
    current = artifacts.current_version(db, stage.id) if stage else None
    if current is None:
        return f"sensor {cfg['sensor']} has no artifact to check"
    outcome = sensors.evaluate(db, execution, stage, current[1], cfg["sensor"], cfg.get("config") or {})
    return None if outcome.status in SATISFYING else f"sensor {cfg['sensor']} returned {outcome.status.value}"


def _attempt(db: Session, key: str, version: HookVersion, scope: HookScope) -> tuple[str | None, int, int]:
    started = time.perf_counter()
    attempts = 0
    failure: str | None = None
    for _ in range(version.max_retries + 1):
        attempts += 1
        try:
            with db.begin_nested():
                failure = _perform(db, version, scope)
        except Exception as exc:  # noqa: BLE001 - a broken hook counts as a failed hook
            failure = f"hook error: {type(exc).__name__}"
        if failure is None:
            break
    elapsed = int((time.perf_counter() - started) * 1000)
    if failure is None and elapsed > version.timeout_ms:
        failure = f"timed out after {elapsed} ms"
    return failure, attempts, elapsed


def run_hooks(db: Session, scope: HookScope, event: str, phase: str = "post") -> tuple[list[str], list[dict[str, Any]]]:
    """Run matching hooks in priority order. Returns blocking failures and the log records written."""
    failures: list[str] = []
    records: list[dict[str, Any]] = []
    for key, version in _active(db, scope.organization_id, event, phase):
        if not _matches(version, scope):
            continue
        failure, attempts, elapsed = _attempt(db, key, version, scope)
        record = {
            "organization_id": scope.organization_id, "project_id": scope.project_id,
            "hook_version_id": version.id, "event": event, "phase": phase, "stage_key": scope.stage_key,
            "status": "failed" if failure else "succeeded", "attempts": attempts,
            "detail": (failure or "ok")[:300], "duration_ms": elapsed,
        }
        db.add(HookExecution(**record))
        records.append(record)
        if failure and version.failure_policy == "fail_closed":
            failures.append(f"{key}: {failure}")
            break
    db.flush()
    return failures, records


def enforce(db: Session, scope: HookScope, event: str, phase: str) -> None:
    failures, records = run_hooks(db, scope, event, phase)
    if failures:
        raise HookBlocked(scope, event, failures, records)


def persist_blocked(db: Session, exc: HookBlocked) -> None:
    """After the refused operation rolled back, keep the record of why it was refused."""
    for record in exc.records:
        db.add(HookExecution(**record))
    append_event(db, chain_key=org_chain(exc.scope.organization_id), event_type="hook.blocked", actor_type="hook",
                 organization_id=exc.scope.organization_id, project_id=exc.scope.project_id,
                 payload={"event": exc.event, "stage": exc.scope.stage_key, "reason": exc.message})
    db.commit()
