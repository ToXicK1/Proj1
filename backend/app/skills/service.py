"""Skills: reusable instructions with immutable versions.

A skill names the tools it needs and the profiles it suits. An agent version pins specific skill
versions; a skill can only be pinned where its tools are already granted to that agent and its
profile is compatible. Pinned versions never change, so a run's instructions are always traceable.
"""

import hashlib
import json
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.models import Profile
from app.agents.tools import grant_problems
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError
from app.organizations.service import require_org_admin
from app.skills.models import Skill, SkillVersion

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_\-]{1,63}$")


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _check(instructions: str, required_tools: list[str], compatible_profiles: list[str]) -> None:
    if not instructions.strip() or len(instructions) > 4000:
        raise AppError(422, "invalid_instructions", "Skill instructions must be 1 to 4000 characters")
    problems = grant_problems(required_tools)
    if problems:
        raise AppError(422, "invalid_tools", "; ".join(problems))


def _write_version(db: Session, skill: Skill, instructions: str, required_tools: list[str],
                   compatible_profiles: list[str]) -> SkillVersion:
    last = db.execute(select(func.max(SkillVersion.version)).where(SkillVersion.skill_id == skill.id)).scalar_one()
    payload = {"instructions": instructions, "required_tools": required_tools,
               "compatible_profiles": compatible_profiles}
    version = SkillVersion(
        id=uuid7(), skill_id=skill.id, version=(last or 0) + 1, instructions=instructions,
        required_tools=required_tools, compatible_profiles=compatible_profiles, sha256=_digest(payload),
    )
    db.add(version)
    db.flush()
    return version


def _profiles_exist(db: Session, organization_id: uuid.UUID, keys: list[str]) -> None:
    known = set(db.execute(select(Profile.key).where(Profile.organization_id == organization_id)).scalars())
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise AppError(422, "unknown_profile", f"Unknown profiles: {', '.join(unknown)}")


def create_skill(db: Session, user: User, *, organization_id: uuid.UUID, key: str, instructions: str,
                 required_tools: list[str], compatible_profiles: list[str]) -> SkillVersion:
    require_org_admin(db, user.id, organization_id)
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Skill key must be lowercase, letters, digits, '-' or '_'")
    _check(instructions, required_tools, compatible_profiles)
    _profiles_exist(db, organization_id, compatible_profiles)
    if db.execute(select(Skill.id).where(Skill.organization_id == organization_id, Skill.key == key)).first():
        raise AppError(409, "skill_exists", "A skill with this key already exists")
    skill = Skill(id=uuid7(), organization_id=organization_id, key=key)
    db.add(skill)
    db.flush()
    version = _write_version(db, skill, instructions, required_tools, compatible_profiles)
    db.commit()
    return version


def add_skill_version(db: Session, user: User, *, organization_id: uuid.UUID, key: str, instructions: str,
                      required_tools: list[str], compatible_profiles: list[str]) -> SkillVersion:
    require_org_admin(db, user.id, organization_id)
    skill = _skill(db, organization_id, key)
    _check(instructions, required_tools, compatible_profiles)
    _profiles_exist(db, organization_id, compatible_profiles)
    version = _write_version(db, skill, instructions, required_tools, compatible_profiles)
    db.commit()
    return version


def _skill(db: Session, organization_id: uuid.UUID, key: str) -> Skill:
    skill = db.execute(select(Skill).where(Skill.organization_id == organization_id, Skill.key == key)).scalar_one_or_none()
    if skill is None:
        raise AppError(404, "unknown_skill", "Skill does not exist")
    return skill


def version_of(db: Session, organization_id: uuid.UUID, key: str, version: int) -> SkillVersion:
    skill = _skill(db, organization_id, key)
    row = db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id,
                                                SkillVersion.version == version)).scalar_one_or_none()
    if row is None:
        raise AppError(404, "unknown_skill_version", "Skill version does not exist")
    return row


def latest_version(db: Session, organization_id: uuid.UUID, key: str) -> SkillVersion:
    skill = _skill(db, organization_id, key)
    row = db.execute(select(SkillVersion).where(SkillVersion.skill_id == skill.id)
                     .order_by(SkillVersion.version.desc())).scalars().first()
    if row is None:
        raise AppError(404, "unknown_skill", "Skill has no version")
    return row


def pin_for_agent(db: Session, organization_id: uuid.UUID, *, skill_keys: list[str], profile_key: str,
                  agent_tools: list[str]) -> list[dict]:
    """Resolve skill keys to their latest versions and check each against the agent it will serve.

    Returns pinned references [{"key", "version"}]. Raises if a skill is incompatible with the
    profile or needs a tool the agent does not hold.
    """
    pins: list[dict] = []
    for key in skill_keys:
        version = latest_version(db, organization_id, key)
        if version.compatible_profiles and profile_key not in version.compatible_profiles:
            raise AppError(422, "skill_not_compatible", f"Skill '{key}' is not for the {profile_key} profile")
        missing = [t for t in version.required_tools if t not in agent_tools]
        if missing:
            raise AppError(422, "skill_tool_missing", f"Skill '{key}' needs tools the agent does not hold: "
                                                      f"{', '.join(missing)}")
        pins.append({"key": key, "version": version.version})
    return pins


def instructions_for_pins(db: Session, organization_id: uuid.UUID, pins: list[dict]) -> str:
    """The text added to an agent's instructions: each pinned skill version, in pin order."""
    blocks = []
    for pin in pins:
        row = version_of(db, organization_id, pin["key"], pin["version"])
        blocks.append(f"Skill '{pin['key']}' (version {pin['version']}):\n{row.instructions}")
    return "\n\n".join(blocks)
