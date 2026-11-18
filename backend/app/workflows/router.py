import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.workflows import service

router = APIRouter(prefix="/api/v1", tags=["workflows"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartIn(_Strict):
    workflow_version_id: uuid.UUID


@router.post("/projects/{project_id}/workflow-executions", status_code=201)
def start(project_id: uuid.UUID, body: StartIn, caller: CsrfCaller, db: DbSession) -> dict:
    execution = service.start_execution(
        db, caller.user, project_id=project_id, workflow_version_id=body.workflow_version_id
    )
    return service.execution_view(db, caller.user, execution.id)


@router.get("/workflow-executions/{execution_id}")
def read(execution_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return service.execution_view(db, caller.user, execution_id)
