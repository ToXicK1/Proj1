import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.organizations.service import require_org_admin
from app.skills import service
from app.skills.models import Skill

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/skills", tags=["skills"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillIn(_Strict):
    key: str = Field(min_length=2, max_length=64)
    instructions: str = Field(min_length=1, max_length=4000)
    required_tools: list[str] = Field(default_factory=list, max_length=10)
    compatible_profiles: list[str] = Field(default_factory=list, max_length=10)
    compatible_stages: list[str] = Field(default_factory=list, max_length=50)
    dependencies: list[str] = Field(default_factory=list, max_length=8)


class SkillVersionIn(_Strict):
    instructions: str = Field(min_length=1, max_length=4000)
    required_tools: list[str] = Field(default_factory=list, max_length=10)
    compatible_profiles: list[str] = Field(default_factory=list, max_length=10)
    compatible_stages: list[str] = Field(default_factory=list, max_length=50)
    dependencies: list[str] = Field(default_factory=list, max_length=8)


@router.post("", status_code=201)
def create(organization_id: uuid.UUID, body: SkillIn, caller: CsrfCaller, db: DbSession) -> dict:
    version = service.create_skill(
        db, caller.user, organization_id=organization_id, key=body.key, instructions=body.instructions,
        required_tools=body.required_tools, compatible_profiles=body.compatible_profiles,
        compatible_stages=body.compatible_stages, dependencies=body.dependencies,
    )
    return {"key": body.key, "version": version.version}


@router.post("/{key}/versions", status_code=201)
def add_version(organization_id: uuid.UUID, key: str, body: SkillVersionIn, caller: CsrfCaller, db: DbSession) -> dict:
    version = service.add_skill_version(
        db, caller.user, organization_id=organization_id, key=key, instructions=body.instructions,
        required_tools=body.required_tools, compatible_profiles=body.compatible_profiles,
        compatible_stages=body.compatible_stages, dependencies=body.dependencies,
    )
    return {"key": key, "version": version.version}


@router.get("")
def list_skills(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    require_org_admin(db, caller.user.id, organization_id)
    items = []
    for skill in db.execute(select(Skill).where(Skill.organization_id == organization_id).order_by(Skill.key)).scalars():
        latest = service.latest_version(db, organization_id, skill.key)
        items.append({"key": skill.key, "version": latest.version, "required_tools": latest.required_tools,
                      "compatible_profiles": latest.compatible_profiles,
                      "compatible_stages": latest.compatible_stages, "dependencies": latest.dependencies})
    return {"items": items}
