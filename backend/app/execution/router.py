"""Execution jobs over HTTP (Phase 1): professionals queue an allowlisted kind of job and read what really happened.
Nothing here runs code: the executor service does, in its own container per job."""

import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.execution import service

router = APIRouter(prefix="/api/v1/projects/{project_id}/executions", tags=["execution"])


class ExecutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=48)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=202)
def request_execution(project_id: uuid.UUID, body: ExecutionIn, caller: CsrfCaller, db: DbSession) -> dict:
    return service.job_out(service.request(db, caller.user, project_id, body.kind, body.payload))


@router.get("")
def list_executions(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": [service.job_out(j) for j in service.recent(db, caller.user, project_id)]}


@router.get("/{job_id}")
def get_execution(project_id: uuid.UUID, job_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.job_out(service.get(db, caller.user, project_id, job_id))
