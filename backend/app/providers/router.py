import uuid
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.core.config import Settings
from app.providers import routing, service
from app.providers.models import AiProvider, ModelRoute, SecretReference

router = APIRouter(prefix="/api/v1/orgs/{organization_id}", tags=["providers"])

ADAPTERS = Literal["anthropic", "openai", "gemini", "openai_compatible", "mock"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    adapter_type: ADAPTERS
    base_url: str | None = Field(default=None, max_length=300)
    # Write-only. Never returned, logged, or audited.
    api_key: str | None = Field(default=None, min_length=8, max_length=512, repr=False)


class KeyIn(_Strict):
    api_key: str = Field(min_length=8, max_length=512, repr=False)


class HealthIn(_Strict):
    model: str = Field(min_length=1, max_length=120)


class FallbackIn(_Strict):
    provider_id: uuid.UUID
    model: str = Field(min_length=1, max_length=120)


class RouteIn(_Strict):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    primary_provider_id: uuid.UUID
    primary_model: str = Field(min_length=1, max_length=120)
    fallbacks: list[FallbackIn] = Field(default_factory=list, max_length=3)

    @field_validator("fallbacks")
    @classmethod
    def _no_duplicates(cls, v: list[FallbackIn]) -> list[FallbackIn]:
        keys = [(f.provider_id, f.model) for f in v]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate fallback")
        return v


def _provider_out(db, provider: AiProvider) -> dict:  # type: ignore[no-untyped-def]
    ref = db.get(SecretReference, provider.secret_reference_id) if provider.secret_reference_id else None
    return {
        "id": str(provider.id),
        "name": provider.name,
        "adapter_type": provider.adapter_type,
        "base_url": provider.base_url,
        "status": provider.status,
        "key_last4": ref.last4 if ref else None,
        "health": {
            "ok": provider.last_health_ok,
            "checked_at": provider.last_health_at.isoformat() if provider.last_health_at else None,
            "error_kind": provider.last_health_error,
        },
    }


def _route_out(route: ModelRoute) -> dict:
    return {
        "id": str(route.id),
        "key": route.key,
        "primary_provider_id": str(route.primary_provider_id),
        "primary_model": route.primary_model,
        "fallbacks": route.fallbacks,
    }


@router.post("/providers", status_code=201)
def create(organization_id: uuid.UUID, body: ProviderIn, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    settings: Settings = request.app.state.settings
    provider = service.create_provider(
        db, settings, caller.user, organization_id=organization_id, name=body.name,
        adapter_type=body.adapter_type, base_url=body.base_url, api_key=body.api_key,
    )
    return _provider_out(db, provider)


@router.get("/providers")
def list_providers(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    service._require_admin(db, caller.user, organization_id)
    rows = db.execute(select(AiProvider).where(AiProvider.organization_id == organization_id)
                      .order_by(AiProvider.name)).scalars()
    return {"items": [_provider_out(db, p) for p in rows]}


@router.post("/providers/{provider_id}/key")
def rotate(organization_id: uuid.UUID, provider_id: uuid.UUID, body: KeyIn, request: Request, caller: CsrfCaller,
           db: DbSession) -> dict:
    settings: Settings = request.app.state.settings
    provider = service.rotate_key(db, settings, caller.user, organization_id=organization_id,
                                  provider_id=provider_id, api_key=body.api_key)
    return _provider_out(db, provider)


@router.post("/providers/{provider_id}/health")
def health(organization_id: uuid.UUID, provider_id: uuid.UUID, body: HealthIn, request: Request, caller: CsrfCaller,
           db: DbSession) -> dict:
    settings: Settings = request.app.state.settings
    return service.probe(db, settings, caller.user, organization_id=organization_id, provider_id=provider_id,
                         model=body.model, transport=request.app.state.provider_transport)


@router.post("/model-routes", status_code=201)
def create_route(organization_id: uuid.UUID, body: RouteIn, caller: CsrfCaller, db: DbSession) -> dict:
    route = service.create_route(
        db, caller.user, organization_id=organization_id, key=body.key,
        primary_provider_id=body.primary_provider_id, primary_model=body.primary_model,
        fallbacks=[f.model_dump(mode="python") for f in body.fallbacks],
    )
    return _route_out(route)


@router.get("/model-routes")
def list_routes(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    service._require_admin(db, caller.user, organization_id)
    rows = db.execute(select(ModelRoute).where(ModelRoute.organization_id == organization_id)
                      .order_by(ModelRoute.key)).scalars()
    return {"items": [_route_out(r) for r in rows]}



class RoutingRuleIn(_Strict):
    task: Literal["lead", "reviewer", "specialist", "answer", "triage"]
    profile: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    route: str = Field(pattern=r"^[a-z][a-z0-9_\-]{1,63}$")
    require_different_provider: bool = False


class RoutingPolicyIn(_Strict):
    rules: list[RoutingRuleIn] = Field(default_factory=list, max_length=60)


@router.get("/routing-policies")
def routing_policies(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"rules": routing.list_policies(db, caller.user, organization_id)}


@router.put("/routing-policies")
def replace_routing_policies(organization_id: uuid.UUID, body: RoutingPolicyIn, caller: CsrfCaller,
                             db: DbSession) -> dict:
    """Which model route each kind of AI task uses, per department if needed. Administrators only."""
    return {"rules": routing.replace_policies(db, caller.user, organization_id,
                                              [r.model_dump() for r in body.rules])}
