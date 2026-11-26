"""The Codebase Explorer over HTTP. The project's Software Developers only; every path must be a file of the
branch's analysis. Indexing is queued (worker, then the executor); everything else reads the stored analysis."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.codebase import service
from app.jobs.api import queue

router = APIRouter(prefix="/api/v1/projects/{project_id}/codebase", tags=["codebase"])
Branch = Query(default="main", min_length=1, max_length=100)
FileType = Literal["source", "test", "config", "docs", "entry", "other"]
Relation = Literal["imports", "re_exports", "requires", "dynamic_import", "tests"]


class IndexIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branch: str = Field(default="main", min_length=1, max_length=100)


@router.get("/status")
def index_status(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession, branch: str = Branch) -> dict:
    return service.status(db, caller.user, project_id, branch)


@router.post("/index", status_code=202)
def index(project_id: uuid.UUID, body: IndexIn, request: Request, tasks: BackgroundTasks, caller: CsrfCaller,
          db: DbSession) -> dict:
    row = service.request_index(db, caller.user, project_id, body.branch)
    out = service.status_out(row)
    queue(request, tasks, db, "codebase.index", {"index_id": str(row.id)},
          dedupe_key=f"codebase:{row.id}:{row.started_at.isoformat()}", project_id=project_id)
    return out


@router.get("/tree")
def tree(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession, branch: str = Branch) -> dict:
    return service.tree(db, caller.user, project_id, branch)


@router.get("/graph")
def graph(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession, branch: str = Branch,
          focus: str | None = Query(default=None, max_length=500), depth: int = Query(default=1, ge=1, le=6),
          transitive: bool = False, types: Annotated[list[FileType] | None, Query()] = None,
          relations: Annotated[list[Relation] | None, Query()] = None, external: bool = False) -> dict:
    return service.graph(db, caller.user, project_id, branch, focus=focus, depth=depth, transitive=transitive,
                         types=list(types or []), relations=list(relations or []), external=external)


@router.get("/file")
def file(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession, branch: str = Branch,
         path: str = Query(min_length=1, max_length=500), history: bool = False) -> dict:
    return service.file_details(db, request.app.state.session_factory, caller.user, project_id, branch, path,
                                history)


@router.get("/impact")
def impact(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession, branch: str = Branch,
           paths: Annotated[list[str] | None, Query(max_length=200)] = None, change_set: uuid.UUID | None = None
           ) -> dict:
    return service.impact(db, caller.user, project_id, branch, [p[:500] for p in paths or []], change_set)


@router.get("/chain")
def chain(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession, branch: str = Branch,
          source: str = Query(min_length=1, max_length=500), target: str = Query(min_length=1, max_length=500)
          ) -> dict:
    return service.dependency_chain(db, caller.user, project_id, branch, source, target)
