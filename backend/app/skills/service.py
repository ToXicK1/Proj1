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
STAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _check(instructions: str, required_tools: list[str], compatible_stages: list[str],
           dependencies: list[str]) -> None:
    if not instructions.strip() or len(instructions) > 4000:
        raise AppError(422, "invalid_instructions", "Skill instructions must be 1 to 4000 characters")
    problems = grant_problems(required_tools)
    if problems:
        raise AppError(422, "invalid_tools", "; ".join(problems))
    bad_stages = [k for k in compatible_stages if not STAGE_PATTERN.match(k)]
    if bad_stages:
        raise AppError(422, "invalid_stage", f"Invalid stage keys: {', '.join(bad_stages)}")
    if len(set(dependencies)) != len(dependencies):
        raise AppError(422, "invalid_dependency", "Dependencies must be unique")


def _closure(db: Session, organization_id: uuid.UUID, pins: list[dict]) -> list[tuple[str, SkillVersion]]:
    """Every pinned version and what it depends on, dependencies first, without repeats.

    Dependencies point at versions that already existed, so this always terminates. Two different
    versions of one skill in the same closure are refused: which text applies would be ambiguous.
    """
    ordered: list[tuple[str, SkillVersion]] = []
    chosen: dict[str, int] = {}

    def claim(key: str, number: int) -> bool:
        if key in chosen and chosen[key] != number:
            raise AppError(422, "skill_version_conflict",
                           f"Skill '{key}' is required at versions {chosen[key]} and {number}")
        return key in chosen

    def visit(pin: dict) -> None:
        key, number = pin["key"], pin["version"]
        if claim(key, number):
            return
        row = version_of(db, organization_id, key, number)
        for dep in row.dependencies:
            visit(dep)
        claim(key, number)
        chosen[key] = number
        ordered.append((key, row))

    for pin in pins:
        visit(pin)
    return ordered


def _write_version(db: Session, organization_id: uuid.UUID, skill: Skill, instructions: str,
                   required_tools: list[str], compatible_profiles: list[str], compatible_stages: list[str],
                   dependencies: list[str]) -> SkillVersion:
    if skill.key in dependencies:
        raise AppError(422, "invalid_dependency", "A skill cannot depend on itself")
    pins = [{"key": key, "version": latest_version(db, organization_id, key).version} for key in dependencies]
    closure = _closure(db, organization_id, pins)
    if any(key == skill.key for key, _ in closure):
        raise AppError(422, "invalid_dependency", f"Skill '{skill.key}' would depend on itself through another skill")
    last = db.execute(select(func.max(SkillVersion.version)).where(SkillVersion.skill_id == skill.id)).scalar_one()
    payload = {"instructions": instructions, "required_tools": required_tools,
               "compatible_profiles": compatible_profiles, "compatible_stages": compatible_stages,
               "dependencies": pins}
    version = SkillVersion(
        id=uuid7(), skill_id=skill.id, version=(last or 0) + 1, instructions=instructions,
        required_tools=required_tools, compatible_profiles=compatible_profiles,
        compatible_stages=compatible_stages, dependencies=pins, sha256=_digest(payload),
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
                 required_tools: list[str], compatible_profiles: list[str],
                 compatible_stages: list[str] | None = None, dependencies: list[str] | None = None) -> SkillVersion:
    require_org_admin(db, user.id, organization_id)
    if not KEY_PATTERN.match(key):
        raise AppError(422, "invalid_key", "Skill key must be lowercase, letters, digits, '-' or '_'")
    stages, deps = compatible_stages or [], dependencies or []
    _check(instructions, required_tools, stages, deps)
    _profiles_exist(db, organization_id, compatible_profiles)
    if db.execute(select(Skill.id).where(Skill.organization_id == organization_id, Skill.key == key)).first():
        raise AppError(409, "skill_exists", "A skill with this key already exists")
    skill = Skill(id=uuid7(), organization_id=organization_id, key=key)
    db.add(skill)
    db.flush()
    version = _write_version(db, organization_id, skill, instructions, required_tools, compatible_profiles,
                             stages, deps)
    db.commit()
    return version


def add_skill_version(db: Session, user: User, *, organization_id: uuid.UUID, key: str, instructions: str,
                      required_tools: list[str], compatible_profiles: list[str],
                      compatible_stages: list[str] | None = None,
                      dependencies: list[str] | None = None) -> SkillVersion:
    require_org_admin(db, user.id, organization_id)
    skill = _skill(db, organization_id, key)
    stages, deps = compatible_stages or [], dependencies or []
    _check(instructions, required_tools, stages, deps)
    _profiles_exist(db, organization_id, compatible_profiles)
    version = _write_version(db, organization_id, skill, instructions, required_tools, compatible_profiles,
                             stages, deps)
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
    """Pin the latest version of each named skill, plus everything those versions depend on.

    Returns [{"key", "version"}] with dependencies first. Every skill in the result must suit the
    profile, and the agent must already hold every tool any of them needs.
    """
    roots = [{"key": key, "version": latest_version(db, organization_id, key).version} for key in skill_keys]
    pins: list[dict] = []
    for key, version in _closure(db, organization_id, roots):
        if version.compatible_profiles and profile_key not in version.compatible_profiles:
            raise AppError(422, "skill_not_compatible", f"Skill '{key}' is not for the {profile_key} profile")
        missing = [t for t in version.required_tools if t not in agent_tools]
        if missing:
            raise AppError(422, "skill_tool_missing", f"Skill '{key}' needs tools the agent does not hold: "
                                                      f"{', '.join(missing)}")
        pins.append({"key": key, "version": version.version})
    return pins


def assert_stage_allowed(db: Session, organization_id: uuid.UUID, pins: list[dict], stage_key: str) -> None:
    """Refuse a run when a pinned skill is limited to other stages."""
    for pin in pins:
        row = version_of(db, organization_id, pin["key"], pin["version"])
        if row.compatible_stages and stage_key not in row.compatible_stages:
            raise AppError(422, "skill_not_compatible", f"Skill '{pin['key']}' cannot be used in stage '{stage_key}'")


def instructions_for_pins(db: Session, organization_id: uuid.UUID, pins: list[dict]) -> str:
    """The text added to an agent's instructions: each pinned skill version, in pin order."""
    blocks = []
    for pin in pins:
        row = version_of(db, organization_id, pin["key"], pin["version"])
        blocks.append(f"Skill '{pin['key']}' (version {pin['version']}):\n{row.instructions}")
    return "\n\n".join(blocks)
