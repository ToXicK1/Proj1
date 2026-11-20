import uuid
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.agents import service
from app.auth.deps import CsrfCaller, CurrentCaller, DbSession

router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["agents"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileIn(_Strict):
    key: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=120)


class AgentIn(_Strict):
    profile: str = Field(min_length=2, max_length=64)
    key: str = Field(min_length=2, max_length=64)
    kind: Literal["lead", "reviewer", "specialist"]
    instructions: str = Field(min_length=1, max_length=4000)
    required_keys: list[str] = Field(min_length=1, max_length=8)
    model_route: str = Field(min_length=2, max_length=64)
    context_sources: list[str] = Field(min_length=1, max_length=4)
    tools: list[str] = Field(default_factory=list, max_length=10)
    clone_of: str | None = Field(default=None, max_length=64)
    skills: list[str] = Field(default_factory=list, max_length=8)
    allow_fallback: bool = True


class VersionIn(_Strict):
    instructions: str = Field(min_length=1, max_length=4000)
    required_keys: list[str] = Field(min_length=1, max_length=8)
    model_route: str = Field(min_length=2, max_length=64)
    context_sources: list[str] = Field(min_length=1, max_length=4)
    tools: list[str] = Field(default_factory=list, max_length=10)
    skills: list[str] = Field(default_factory=list, max_length=8)
    allow_fallback: bool = True


@router.post("/profiles", status_code=201)
def create_profile(organization_id: uuid.UUID, body: ProfileIn, caller: CsrfCaller, db: DbSession) -> dict:
    profile = service.create_profile(db, caller.user, organization_id=organization_id, key=body.key, name=body.name)
    return {"key": profile.key, "name": profile.name}


@router.post("/agents", status_code=201)
def create_agent(organization_id: uuid.UUID, body: AgentIn, caller: CsrfCaller, db: DbSession) -> dict:
    agent, version = service.create_agent(
        db, caller.user, organization_id=organization_id, profile_key=body.profile, key=body.key,
        kind=body.kind, instructions=body.instructions, required_keys=body.required_keys,
        model_route=body.model_route, context_sources=body.context_sources, tools=body.tools,
        clone_of=body.clone_of, skills=body.skills, allow_fallback=body.allow_fallback,
    )
    return {"key": agent.key, "kind": agent.kind, "version": version.version}


@router.post("/agents/{key}/versions", status_code=201)
def add_version(organization_id: uuid.UUID, key: str, body: VersionIn, caller: CsrfCaller, db: DbSession) -> dict:
    version = service.add_version(
        db, caller.user, organization_id=organization_id, key=key, instructions=body.instructions,
        required_keys=body.required_keys, model_route=body.model_route, context_sources=body.context_sources,
        tools=body.tools, skills=body.skills, allow_fallback=body.allow_fallback,
    )
    return {"key": key, "version": version.version}


@router.get("/agent-registry")
def agent_registry(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    """Every department's agents: leads by step, independent reviewers and support specialists, with their current
    version, route, tools and whether they are independent of each other."""
    return {"departments": service.registry(db, caller.user, organization_id)}


@router.get("/agents")
def list_agents(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    from app.organizations.service import require_org_admin

    require_org_admin(db, caller.user.id, organization_id)
    return {"items": service.list_agents(db, organization_id)}
