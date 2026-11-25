"""The project repository over HTTP (Phase 1b). Every operation is an executor job; nothing here runs git."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.repos import service

router = APIRouter(prefix="/api/v1/projects/{project_id}/repository", tags=["repository"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileIn(_Strict):
    path: str = Field(min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=400_000)
    delete: bool = False


class CommitIn(_Strict):
    branch: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    files: list[FileIn] = Field(min_length=1, max_length=200)


class ChangeSetIn(_Strict):
    branch: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)


class DecisionIn(_Strict):
    decision: Literal["approve", "request_changes"]
    reviewed_sha: str = Field(min_length=40, max_length=40)  # the commit the reviewer actually looked at
    note: str = Field(default="", max_length=2000)


def _factory(request: Request):
    return request.app.state.session_factory


@router.get("")
def repository(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.status(db, caller.user, project_id)


@router.post("", status_code=201)
def create(project_id: uuid.UUID, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    return service.create(db, _factory(request), caller.user, project_id)


@router.get("/tree")
def tree(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession,
         ref: str = Query("main", max_length=100), path: Annotated[list[str] | None, Query()] = None) -> dict:
    return service.read(db, _factory(request), caller.user, project_id, ref, path)


@router.get("/log")
def log(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession,
        ref: str = Query("main", max_length=100)) -> dict:
    return service.log(db, _factory(request), caller.user, project_id, ref)


@router.get("/diff")
def diff(project_id: uuid.UUID, request: Request, caller: CurrentCaller, db: DbSession,
         head: str = Query(max_length=100), base: str = Query("main", max_length=100)) -> dict:
    return service.diff(db, _factory(request), caller.user, project_id, base, head)


@router.post("/commits", status_code=201)
def commit(project_id: uuid.UUID, body: CommitIn, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    return service.commit(db, _factory(request), caller.user, project_id, branch=body.branch, message=body.message,
                          files=[f.model_dump(exclude_none=True) for f in body.files])


@router.get("/change-sets")
def change_sets(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": service.list_change_sets(db, caller.user, project_id)}


@router.post("/change-sets", status_code=201)
def open_change_set(project_id: uuid.UUID, body: ChangeSetIn, request: Request, caller: CsrfCaller,
                    db: DbSession) -> dict:
    return service.open_change_set(db, _factory(request), caller.user, project_id, branch=body.branch,
                                   title=body.title, description=body.description)


@router.post("/change-sets/{change_set_id}/decision")
def decide(project_id: uuid.UUID, change_set_id: uuid.UUID, body: DecisionIn, request: Request, caller: CsrfCaller,
           db: DbSession) -> dict:
    return service.decide(db, _factory(request), caller.user, project_id, change_set_id, decision=body.decision,
                          note=body.note, reviewed_sha=body.reviewed_sha)


@router.post("/change-sets/{change_set_id}/merge")
def merge(project_id: uuid.UUID, change_set_id: uuid.UUID, request: Request, caller: CsrfCaller,
          db: DbSession) -> dict:
    return service.merge(db, _factory(request), caller.user, project_id, change_set_id)
