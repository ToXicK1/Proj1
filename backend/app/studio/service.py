"""Workflow Studio: organization workflows move from an editable draft to an immutable published version.

A draft may be invalid. Publishing is an administrator's action and refuses anything the compiler or the
organization's own configuration rejects, so an invalid workflow can never be started.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents import service as agents
from app.agents.models import AgentConfiguration, Profile
from app.agents.tools import GRANTABLE_THIS_MILESTONE, TOOL_CATALOG
from app.approvals.policy import KNOWN_ROLES
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks import service as hooks
from app.organizations.service import require_org_admin
from app.providers.models import ModelRoute
from app.providers.tasks import AI_TASKS
from app.rules.models import KINDS, SCOPES
from app.sensors.registry import SENSORS
from app.studio.models import WorkflowDraft
from app.workflows.compiler import CompiledWorkflow, CompileError, WorkflowSpec, compile_workflow
from app.workflows.models import WorkflowDefinition, WorkflowVersion
from app.workflows.service import store_version
from app.workflows.work import KNOWN_WORK, WORK_FUNCTIONS, WorkContext

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]{1,63}$")
MAX_SPEC_BYTES = 256_000
MAX_STAGES = 100
_SAMPLE = WorkContext(project_name="Sample", project_description="Sample description", project_type="Custom Project")


def _encoded_size(spec: dict[str, Any]) -> int:
    return len(json.dumps(spec, separators=(",", ":")).encode())


def _check_key(key: str) -> None:
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Workflow key must be lowercase letters, digits, '-' or '_'")


def catalog(db: Session, user: User, organization_id: uuid.UUID) -> dict[str, Any]:
    """Everything the editors may choose from. Choices come from the platform, never from free text."""
    require_org_admin(db, user.id, organization_id)
    profiles = db.execute(select(Profile).where(Profile.organization_id == organization_id)
                          .order_by(Profile.key)).scalars()
    routes = db.execute(select(ModelRoute.key).where(ModelRoute.organization_id == organization_id)
                        .order_by(ModelRoute.key)).scalars()
    return {
        "work": [{"key": key, "ai": key in AI_TASKS} for key in sorted(KNOWN_WORK)],
        "roles": sorted(KNOWN_ROLES),
        "policy_types": ["single", "any_of", "all_of", "role_based", "sequential"],
        "sensors": [{"key": s.key, "category": s.category, "description": s.description,
                     "evidence_kind": s.evidence_kind, "config_schema": s.config.model_json_schema()}
                    for s in SENSORS.values()],
        "profiles": [{"key": p.key, "name": p.name} for p in profiles],
        "agents": agents.list_agents(db, organization_id),
        "model_routes": list(routes),
        "tools": [{"key": name, "permission_class": str(cls), "grantable": cls in GRANTABLE_THIS_MILESTONE}
                  for name, cls in TOOL_CATALOG.items()],
        "context_sources": {"lead": sorted(agents.LEAD_SOURCES), "reviewer": sorted(agents.REVIEWER_SOURCES)},
        "rule_scopes": list(SCOPES),
        "rule_kinds": list(KINDS),
        "hook_events": sorted(hooks.EVENTS),
        "hook_pre_events": sorted(hooks.PRE_EVENTS),
        "hook_blockable": sorted([event, phase] for event, phase in hooks.BLOCKABLE),
        "hook_actions": hooks.ACTION_PERMISSIONS,
    }


def _output_keys(db: Session, organization_id: uuid.UUID, stage: Any) -> set[str] | None:
    """The keys this stage's work will produce, or None when that cannot be known here."""
    if stage.agent:
        try:
            return set(agents.latest(db, organization_id, stage.agent).version.required_keys)
        except AppError:
            return None
    if stage.work in AI_TASKS:
        return set(AI_TASKS[stage.work].required_keys)
    function = WORK_FUNCTIONS.get(stage.work)
    return set(function(_SAMPLE)) if function else None


def _reference_problems(db: Session, organization_id: uuid.UUID, spec: WorkflowSpec) -> list[str]:
    profile_rows = db.execute(select(Profile).where(Profile.organization_id == organization_id)).scalars().all()
    profile_by_id = {p.id: p.key for p in profile_rows}
    found = {a.key: a for a in db.execute(select(AgentConfiguration).where(
        AgentConfiguration.organization_id == organization_id)).scalars()}
    routes = set(db.execute(select(ModelRoute.key).where(ModelRoute.organization_id == organization_id)).scalars())
    problems: list[str] = []
    for i, stage in enumerate(spec.stages):
        path = f"stages[{i}]"
        if stage.profile and stage.profile not in profile_by_id.values():
            problems.append(f"{path}.profile: unknown profile '{stage.profile}'")
        if stage.model_route and stage.model_route not in routes:
            problems.append(f"{path}.model_route: unknown model route '{stage.model_route}'")
        lead = found.get(stage.agent) if stage.agent else None
        reviewer = found.get(stage.reviewer) if stage.reviewer else None
        if stage.agent and lead is None:
            problems.append(f"{path}.agent: unknown agent '{stage.agent}'")
        elif lead is not None:
            if lead.kind != "lead":
                problems.append(f"{path}.agent: '{stage.agent}' is not a lead agent")
            if stage.profile and profile_by_id.get(lead.profile_id) != stage.profile:
                problems.append(f"{path}.agent: '{stage.agent}' does not belong to profile '{stage.profile}'")
        if stage.reviewer and reviewer is None:
            problems.append(f"{path}.reviewer: unknown agent '{stage.reviewer}'")
        elif reviewer is not None:
            if reviewer.kind != "reviewer":
                problems.append(f"{path}.reviewer: '{stage.reviewer}' is not a reviewer agent")
            if lead is not None and lead.lineage_root_id == reviewer.lineage_root_id:
                problems.append(f"{path}.reviewer: '{stage.reviewer}' is not independent of the lead agent")
        produced = _output_keys(db, organization_id, stage)
        if produced is not None:
            problems += [f"{path}.output_required_keys: this work never produces '{key}'"
                         for key in stage.output_required_keys if key not in produced]
    return problems


def check(db: Session, organization_id: uuid.UUID, raw: dict[str, Any]) -> tuple[CompiledWorkflow | None, list[str]]:
    """Every reason this specification cannot be published. Reports all problems at once."""
    if _encoded_size(raw) > MAX_SPEC_BYTES:
        return None, [f"workflow: larger than {MAX_SPEC_BYTES} bytes"]
    problems: list[str] = []
    compiled: CompiledWorkflow | None = None
    try:
        compiled = compile_workflow(raw, known_work=set(KNOWN_WORK))
    except CompileError as exc:
        problems += exc.problems
    try:
        spec = WorkflowSpec.model_validate(raw)
    except ValidationError:
        return None, problems  # the compiler has already reported the shape problems
    if not KEY_PATTERN.match(spec.key):
        problems.append("key: must be lowercase letters, digits, '-' or '_'")
    if len(spec.stages) > MAX_STAGES:
        problems.append(f"stages: at most {MAX_STAGES} stages")
    if db.execute(select(WorkflowDefinition.id).where(WorkflowDefinition.organization_id.is_(None),
                                                      WorkflowDefinition.key == spec.key)).first():
        problems.append(f"key: '{spec.key}' is reserved by a platform template")
    problems += _reference_problems(db, organization_id, spec)
    return (compiled if not problems else None), problems


def validate(db: Session, user: User, organization_id: uuid.UUID, raw: dict[str, Any]) -> dict[str, Any]:
    require_org_admin(db, user.id, organization_id)
    _, problems = check(db, organization_id, raw)
    return {"valid": not problems, "problems": problems}


def _draft_out(row: WorkflowDraft) -> dict[str, Any]:
    return {"key": row.key, "name": row.name, "spec": row.spec_json, "revision": row.revision,
            "updated_at": row.updated_at.isoformat()}


def _locked_draft(db: Session, organization_id: uuid.UUID, key: str) -> WorkflowDraft | None:
    return db.execute(select(WorkflowDraft).where(WorkflowDraft.organization_id == organization_id,
                                                  WorkflowDraft.key == key).with_for_update()).scalar_one_or_none()


def save_draft(db: Session, user: User, *, organization_id: uuid.UUID, key: str, spec: dict[str, Any],
               expected_revision: int | None) -> dict[str, Any]:
    require_org_admin(db, user.id, organization_id)
    _check_key(key)
    if spec.get("key") != key:
        raise AppError(422, "key_mismatch", "The workflow key must match the draft being saved")
    if _encoded_size(spec) > MAX_SPEC_BYTES:
        raise AppError(413, "workflow_too_large", "This workflow is too large")
    name = str(spec.get("name") or key).strip()[:120] or key
    row = _locked_draft(db, organization_id, key)
    if (row.revision if row else None) != expected_revision:
        db.rollback()
        raise AppError(409, "draft_conflict", "This draft changed since you opened it. Reload it first")
    if row is None:
        row = WorkflowDraft(id=uuid7(), organization_id=organization_id, key=key, name=name, spec_json=spec,
                            revision=1, updated_by=user.id)
        db.add(row)
    else:
        row.name, row.spec_json, row.revision = name, spec, row.revision + 1
        row.updated_by, row.updated_at = user.id, datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "draft_conflict", "This draft changed since you opened it. Reload it first") from exc
    return _draft_out(row)


def _org_definition(db: Session, organization_id: uuid.UUID, key: str) -> WorkflowDefinition | None:
    return db.execute(select(WorkflowDefinition).where(WorkflowDefinition.organization_id == organization_id,
                                                       WorkflowDefinition.key == key)).scalar_one_or_none()


def _versions(db: Session, definition_id: uuid.UUID) -> list[WorkflowVersion]:
    return list(db.execute(select(WorkflowVersion).where(WorkflowVersion.definition_id == definition_id)
                           .order_by(WorkflowVersion.version.desc())).scalars())


def _version_out(v: WorkflowVersion) -> dict[str, Any]:
    return {"id": str(v.id), "version": v.version, "sha256": v.sha256, "created_at": v.created_at.isoformat()}


def publish(db: Session, user: User, *, organization_id: uuid.UUID, key: str, expected_revision: int) -> dict[str, Any]:
    require_org_admin(db, user.id, organization_id)
    try:
        draft = _locked_draft(db, organization_id, key)  # also serializes publishing of this workflow
        if draft is None:
            raise not_found()
        if draft.revision != expected_revision:
            raise AppError(409, "draft_conflict", "This draft changed since you opened it. Reload it first")
        compiled, problems = check(db, organization_id, draft.spec_json)
        if compiled is None:
            raise AppError(422, "invalid_workflow", "This workflow cannot be published", problems=problems)
        definition = _org_definition(db, organization_id, key)
        latest = _versions(db, definition.id)[0] if definition else None
        if latest is not None and latest.sha256 == compiled.sha256:
            raise AppError(409, "no_changes", "This draft matches the latest published version")
        version = store_version(db, compiled, organization_id=organization_id, published_by=user.id)
        append_event(db, chain_key=org_chain(organization_id), event_type="workflow.published", actor_type="human",
                     actor_id=str(user.id), organization_id=organization_id,
                     payload={"workflow_key": key, "version": version.version, "sha256": version.sha256})
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _version_out(version)


def list_workflows(db: Session, user: User, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    require_org_admin(db, user.id, organization_id)
    drafts = {d.key: d for d in db.execute(select(WorkflowDraft).where(
        WorkflowDraft.organization_id == organization_id)).scalars()}
    items: dict[tuple[str, str], dict[str, Any]] = {}
    for d in db.execute(select(WorkflowDefinition).where(or_(
            WorkflowDefinition.organization_id.is_(None),
            WorkflowDefinition.organization_id == organization_id))).scalars():
        scope = "platform" if d.organization_id is None else "organization"
        versions = _versions(db, d.id)
        items[(scope, d.key)] = {"key": d.key, "name": d.name, "scope": scope,
                                 "latest": _version_out(versions[0]) if versions else None,
                                 "draft_revision": drafts[d.key].revision if scope != "platform" and d.key in drafts
                                 else None}
    for key, draft in drafts.items():
        items.setdefault(("organization", key), {"key": key, "name": draft.name, "scope": "organization",
                                                 "latest": None, "draft_revision": draft.revision})
    return [items[k] for k in sorted(items)]


def _visible_definition(db: Session, organization_id: uuid.UUID, key: str) -> WorkflowDefinition | None:
    return _org_definition(db, organization_id, key) or db.execute(select(WorkflowDefinition).where(
        WorkflowDefinition.organization_id.is_(None), WorkflowDefinition.key == key)).scalar_one_or_none()


def get_workflow(db: Session, user: User, organization_id: uuid.UUID, key: str) -> dict[str, Any]:
    require_org_admin(db, user.id, organization_id)
    draft = db.execute(select(WorkflowDraft).where(WorkflowDraft.organization_id == organization_id,
                                                   WorkflowDraft.key == key)).scalar_one_or_none()
    definition = _visible_definition(db, organization_id, key)
    if draft is None and definition is None:
        raise not_found()
    versions = _versions(db, definition.id) if definition else []
    return {"key": key, "scope": "platform" if definition and definition.organization_id is None else "organization",
            "draft": _draft_out(draft) if draft else None,
            "versions": [{**_version_out(v), "spec": v.spec_json} for v in versions]}


def export_spec(db: Session, user: User, organization_id: uuid.UUID, key: str, fmt: str,
                version_number: int | None) -> dict[str, str]:
    """A published version, or the draft when nothing is named and a draft exists."""
    detail = get_workflow(db, user, organization_id, key)
    if version_number is not None:
        spec = next((v["spec"] for v in detail["versions"] if v["version"] == version_number), None)
    elif detail["draft"]:
        spec = detail["draft"]["spec"]
    else:
        spec = detail["versions"][0]["spec"] if detail["versions"] else None
    if spec is None:
        raise not_found()
    content = yaml.safe_dump(spec, sort_keys=False) if fmt == "yaml" else json.dumps(spec, indent=2)
    return {"filename": f"{key}.{fmt}", "content": content}


def _parse(fmt: str, content: str) -> dict[str, Any]:
    invalid = AppError(422, "invalid_import", f"This file is not a valid {fmt.upper()} workflow")
    try:
        if fmt == "yaml":
            # Aliases can expand a small file into a huge document, and a workflow never needs them.
            if any(isinstance(e, yaml.AliasEvent) for e in yaml.parse(content, Loader=yaml.SafeLoader)):
                raise invalid
            data = yaml.safe_load(content)
        else:
            data = json.loads(content)
        data = json.loads(json.dumps(data))  # keeps plain JSON values only
    except (ValueError, TypeError, RecursionError, yaml.YAMLError) as exc:
        raise invalid from exc
    if not isinstance(data, dict) or not isinstance(data.get("key"), str):
        raise invalid
    return data


def import_spec(db: Session, user: User, *, organization_id: uuid.UUID, fmt: str, content: str,
                expected_revision: int | None) -> dict[str, Any]:
    """Imported content only ever becomes a draft. It is checked again when published."""
    require_org_admin(db, user.id, organization_id)
    spec = _parse(fmt, content)
    draft = save_draft(db, user, organization_id=organization_id, key=spec["key"], spec=spec,
                       expected_revision=expected_revision)
    _, problems = check(db, organization_id, spec)
    return {"draft": draft, "problems": problems}
