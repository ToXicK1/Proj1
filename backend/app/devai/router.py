"""The Developer AI over HTTP (Phase 2e). Asking only queues the work; the worker runs it, and every effect it has
goes through the executor's tools on the run's own branch."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.devai import service
from app.jobs.api import queue

router = APIRouter(prefix="/api/v1/projects/{project_id}/developer-ai", tags=["developer-ai"])


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(default="", max_length=4000)
    story_item_id: uuid.UUID | None = None
    base_branch: str = Field(default="main", min_length=1, max_length=100)


@router.post("", status_code=202)
def start(project_id: uuid.UUID, body: StartIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
          db: DbSession) -> dict:
    row = service.start(db, caller.user, project_id, task=body.task, story_item_id=body.story_item_id,
                        base_branch=body.base_branch)
    out = service.run_out(db, row)
    queue(request, tasks, db, "developer_ai.run", {"run_id": str(row.id)}, dedupe_key=f"developer-ai:{row.id}",
          project_id=project_id)
    return out


@router.get("")
def runs(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": [service.run_out(db, r) for r in service.recent(db, caller.user, project_id)]}


@router.get("/stories")
def stories(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.stories(db, caller.user, project_id)}


@router.get("/{run_id}")
def one(project_id: uuid.UUID, run_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.run_out(db, service.get(db, caller.user, project_id, run_id))


@router.post("/{run_id}/cancel")
def cancel(project_id: uuid.UUID, run_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    return service.run_out(db, service.cancel(db, caller.user, project_id, run_id))
