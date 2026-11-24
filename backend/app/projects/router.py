import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import CsrfCaller, CurrentCaller, DbSession
from app.projects import service
from app.projects.models import Project

router = APIRouter(prefix="/api/v1", tags=["projects"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectCreateIn(_Strict):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    project_type: str = Field(min_length=1, max_length=64)
    owner_user_id: uuid.UUID | None = None  # the client, chosen by an administrator


class ProjectOut(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str
    project_type: str
    status: str

    @classmethod
    def of(cls, p: Project) -> "ProjectOut":
        return cls(
            id=str(p.id),
            organization_id=str(p.organization_id),
            name=p.name,
            description=p.description,
            project_type=p.project_type,
            status=p.status,
        )


@router.post("/orgs/{organization_id}/projects", status_code=201)
def create_project(
    organization_id: uuid.UUID, body: ProjectCreateIn, request: Request, caller: CsrfCaller, db: DbSession
) -> dict:
    project = service.create_project(
        db,
        caller.user,
        organization_id=organization_id,
        name=body.name,
        description=body.description,
        project_type=body.project_type,
        owner_user_id=body.owner_user_id,
        managed=request.app.state.settings.account_mode == "managed",
    )
    return ProjectOut.of(project).model_dump()


class ManagerIn(_Strict):
    user_id: uuid.UUID | None = None


@router.put("/projects/{project_id}/manager")
def assign_manager(project_id: uuid.UUID, body: ManagerIn, caller: CsrfCaller, db: DbSession) -> dict:
    """Administrators only: the project's Project Manager (RD-20)."""
    project = service.assign_manager(db, caller.user, project_id, body.user_id)
    return {"project_id": str(project.id),
            "project_manager_id": str(project.project_manager_id) if project.project_manager_id else None}


@router.get("/projects")
def list_projects(caller: CurrentCaller, db: DbSession) -> dict:
    items = service.projects_for_user(db, caller.user.id)
    return {"items": [ProjectOut.of(p).model_dump() for p in items]}


@router.get("/projects/{project_id}")
def get_project(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return ProjectOut.of(service.project_for_user(db, caller.user.id, project_id)).model_dump()
