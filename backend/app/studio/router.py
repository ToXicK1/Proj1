import uuid
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.portal import lifecycle
from app.studio import service
from app.studio.service import MAX_SPEC_BYTES

router = APIRouter(prefix="/api/v1/orgs/{organization_id}/studio", tags=["studio"])
Format = Literal["json", "yaml"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpecIn(_Strict):
    spec: dict[str, Any]


class DraftIn(SpecIn):
    expected_revision: int | None = Field(default=None, ge=1)


class PublishIn(_Strict):
    expected_revision: int = Field(ge=1)


class LifecycleIn(_Strict):
    model_route: str = Field(min_length=2, max_length=64)


class ImportIn(_Strict):
    format: Format
    content: str = Field(min_length=1, max_length=MAX_SPEC_BYTES)
    expected_revision: int | None = Field(default=None, ge=1)


@router.post("/default-lifecycle", status_code=201)
def default_lifecycle(organization_id: uuid.UUID, body: LifecycleIn, caller: CsrfCaller, db: DbSession) -> dict:
    return lifecycle.provision(db, caller.user, organization_id, body.model_route)


@router.get("/catalog")
def catalog(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.catalog(db, caller.user, organization_id)


@router.get("/workflows")
def list_workflows(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.list_workflows(db, caller.user, organization_id)}


@router.post("/validate")
def validate(organization_id: uuid.UUID, body: SpecIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.validate(db, caller.user, organization_id, body.spec)


@router.post("/import", status_code=201)
def import_workflow(organization_id: uuid.UUID, body: ImportIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.import_spec(db, caller.user, organization_id=organization_id, fmt=body.format,
                               content=body.content, expected_revision=body.expected_revision)


@router.get("/workflows/{key}")
def get_workflow(organization_id: uuid.UUID, key: str, caller: CurrentCaller, db: DbSession) -> dict:
    return service.get_workflow(db, caller.user, organization_id, key)


@router.put("/workflows/{key}/draft")
def save_draft(organization_id: uuid.UUID, key: str, body: DraftIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.save_draft(db, caller.user, organization_id=organization_id, key=key, spec=body.spec,
                              expected_revision=body.expected_revision)


@router.post("/workflows/{key}/publish", status_code=201)
def publish(organization_id: uuid.UUID, key: str, body: PublishIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.publish(db, caller.user, organization_id=organization_id, key=key,
                           expected_revision=body.expected_revision)


@router.get("/workflows/{key}/export")
def export_workflow(organization_id: uuid.UUID, key: str, caller: CurrentCaller, db: DbSession,
                    format: Format = "json", version: int | None = Query(default=None, ge=1)) -> dict:
    return service.export_spec(db, caller.user, organization_id, key, format, version)
