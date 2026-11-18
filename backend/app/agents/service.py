"""Agents and profiles: registry, immutable versions, lineage and independence.

Rules:
- an agent's behaviour changes only by a new version; running work records the version it used
- lead agents may read project input and feedback; reviewers may read only the artifact under review
- a reviewer must not share a lineage root with its lead; a clone of the lead is not independent
- tools are granted from the catalogue and only at the classes this milestone allows
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.models import AgentConfiguration, AgentConfigVersion, Profile
from app.agents.tools import grant_problems
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError
from app.organizations.service import require_org_admin

LEAD_SOURCES = frozenset({"project_input", "feedback"})
REVIEWER_SOURCES = frozenset({"stage_artifact"})
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]{1,63}$")
KEY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ReviewerNotIndependent(Exception):
    pass


@dataclass(frozen=True)
class Resolved:
    agent: AgentConfiguration
    version: AgentConfigVersion


def _check_keys(required_keys: list[str]) -> None:
    if not required_keys or len(required_keys) > 8:
        raise AppError(422, "invalid_keys", "An agent needs between 1 and 8 output keys")
    for key in required_keys:
        if not KEY_NAME_PATTERN.match(key):
            raise AppError(422, "invalid_keys", f"Output key '{key}' must be lowercase snake_case")
    if len(set(required_keys)) != len(required_keys):
        raise AppError(422, "invalid_keys", "Output keys must be unique")


def _check_version_fields(kind: str, instructions: str, required_keys: list[str], context_sources: list[str],
                          tools: list[str]) -> None:
    if not instructions.strip() or len(instructions) > 4000:
        raise AppError(422, "invalid_instructions", "Instructions must be 1 to 4000 characters")
    _check_keys(required_keys)
    allowed = LEAD_SOURCES if kind == "lead" else REVIEWER_SOURCES
    if not context_sources or not set(context_sources) <= allowed:
        raise AppError(422, "invalid_context", f"A {kind} may read only: {', '.join(sorted(allowed))}")
    problems = grant_problems(tools)
    if problems:
        raise AppError(422, "invalid_tools", "; ".join(problems))


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def create_profile(db: Session, user: User, *, organization_id: uuid.UUID, key: str, name: str) -> Profile:
    require_org_admin(db, user.id, organization_id)
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Profile key must be lowercase, letters, digits, '-' or '_'")
    if db.execute(select(Profile.id).where(Profile.organization_id == organization_id, Profile.key == key)).first():
        raise AppError(409, "profile_exists", "A profile with this key already exists")
    profile = Profile(id=uuid7(), organization_id=organization_id, key=key, name=name.strip())
    db.add(profile)
    db.commit()
    return profile


def _profile(db: Session, organization_id: uuid.UUID, key: str) -> Profile:
    profile = db.execute(select(Profile).where(Profile.organization_id == organization_id,
                                               Profile.key == key)).scalar_one_or_none()
    if profile is None:
        raise AppError(404, "unknown_profile", "Profile does not exist")
    return profile


def create_agent(
    db: Session,
    user: User,
    *,
    organization_id: uuid.UUID,
    profile_key: str,
    key: str,
    kind: str,
    instructions: str,
    required_keys: list[str],
    model_route: str,
    context_sources: list[str],
    tools: list[str],
    clone_of: str | None = None,
    skills: list[str] | None = None,
    allow_fallback: bool = True,
) -> tuple[AgentConfiguration, AgentConfigVersion]:
    require_org_admin(db, user.id, organization_id)
    if kind not in ("lead", "reviewer"):
        raise AppError(422, "invalid_kind", "Kind must be lead or reviewer")
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Agent key must be lowercase, letters, digits, '-' or '_'")
    _check_version_fields(kind, instructions, required_keys, context_sources, tools)
    profile = _profile(db, organization_id, profile_key)
    if db.execute(select(AgentConfiguration.id).where(AgentConfiguration.organization_id == organization_id,
                                                      AgentConfiguration.key == key)).first():
        raise AppError(409, "agent_exists", "An agent with this key already exists")

    root_id = None
    if clone_of is not None:
        source = _agent(db, organization_id, clone_of)
        root_id = source.lineage_root_id
    agent_id = uuid7()
    agent = AgentConfiguration(
        id=agent_id, organization_id=organization_id, profile_id=profile.id, key=key, kind=kind,
        lineage_root_id=root_id or agent_id,  # a new lineage roots at itself; a clone joins its source's
    )
    db.add(agent)
    db.flush()
    pins = _pins(db, organization_id, skills or [], profile.key, tools)
    version = _new_version(db, agent, instructions, required_keys, model_route, context_sources, tools,
                           skills=pins, allow_fallback=allow_fallback)
    db.commit()
    return agent, version


def _agent(db: Session, organization_id: uuid.UUID, key: str) -> AgentConfiguration:
    agent = db.execute(select(AgentConfiguration).where(AgentConfiguration.organization_id == organization_id,
                                                        AgentConfiguration.key == key)).scalar_one_or_none()
    if agent is None:
        raise AppError(404, "unknown_agent", "Agent does not exist")
    return agent


def _pins(db: Session, organization_id: uuid.UUID, skill_keys: list[str], profile_key: str,
          tools: list[str]) -> list[dict]:
    from app.skills.service import pin_for_agent

    return pin_for_agent(db, organization_id, skill_keys=skill_keys, profile_key=profile_key, agent_tools=tools)


def _new_version(db: Session, agent: AgentConfiguration, instructions: str, required_keys: list[str],
                 model_route: str, context_sources: list[str], tools: list[str], *,
                 skills: list[dict] | None = None, allow_fallback: bool = True) -> AgentConfigVersion:
    last = db.execute(select(func.max(AgentConfigVersion.version)).where(
        AgentConfigVersion.agent_id == agent.id)).scalar_one()
    pins = skills or []
    payload = {"instructions": instructions, "required_keys": required_keys, "model_route": model_route,
               "context_sources": context_sources, "tools": tools, "kind": agent.kind, "skills": pins,
               "allow_fallback": allow_fallback}
    version = AgentConfigVersion(
        id=uuid7(), agent_id=agent.id, version=(last or 0) + 1, instructions=instructions,
        required_keys=required_keys, model_route=model_route, context_sources=context_sources,
        tools=tools, sha256=_digest(payload), skills=pins, allow_fallback=allow_fallback,
    )
    db.add(version)
    db.flush()
    return version


def add_version(db: Session, user: User, *, organization_id: uuid.UUID, key: str, instructions: str,
                required_keys: list[str], model_route: str, context_sources: list[str],
                tools: list[str], skills: list[str] | None = None,
                allow_fallback: bool = True) -> AgentConfigVersion:
    require_org_admin(db, user.id, organization_id)
    agent = _agent(db, organization_id, key)
    _check_version_fields(agent.kind, instructions, required_keys, context_sources, tools)
    profile = db.get(Profile, agent.profile_id)
    pins = _pins(db, organization_id, skills or [], profile.key, tools)
    version = _new_version(db, agent, instructions, required_keys, model_route, context_sources, tools,
                           skills=pins, allow_fallback=allow_fallback)
    db.commit()
    return version


def latest(db: Session, organization_id: uuid.UUID, key: str) -> Resolved:
    agent = _agent(db, organization_id, key)
    version = db.execute(
        select(AgentConfigVersion).where(AgentConfigVersion.agent_id == agent.id)
        .order_by(AgentConfigVersion.version.desc())
    ).scalars().first()
    if version is None:
        raise AppError(404, "unknown_agent", "Agent has no version")
    return Resolved(agent=agent, version=version)


def assert_independent(lead: AgentConfiguration, reviewer: AgentConfiguration) -> None:
    """A reviewer must not be the lead, nor a clone of it. Refused at run time, not just in the compiler."""
    if lead.id == reviewer.id or lead.lineage_root_id == reviewer.lineage_root_id:
        raise ReviewerNotIndependent("reviewer shares a lineage with the lead agent")


def list_agents(db: Session, organization_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(AgentConfiguration, Profile).join(Profile, Profile.id == AgentConfiguration.profile_id)
                      .where(AgentConfiguration.organization_id == organization_id)
                      .order_by(AgentConfiguration.key)).all()
    out = []
    for agent, profile in rows:
        version = db.execute(select(AgentConfigVersion).where(AgentConfigVersion.agent_id == agent.id)
                             .order_by(AgentConfigVersion.version.desc())).scalars().first()
        out.append({
            "key": agent.key,
            "kind": agent.kind,
            "profile": profile.key,
            "version": version.version if version else None,
            "model_route": version.model_route if version else None,
            "context_sources": version.context_sources if version else [],
            "tools": version.tools if version else [],
        })
    return out
