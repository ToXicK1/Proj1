import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.auth.deps import AppSettings, CsrfCaller, CurrentCaller, DbSession
from app.auth.service import EMAIL_PATTERN
from app.core.errors import AppError
from app.organizations import members

router = APIRouter(prefix="/api/v1", tags=["members"])

OrgRole = Literal["org_admin", "member"]
ProjectRole = Literal["project_owner", "internal_reviewer", "team_member", "viewer"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InviteIn(_Strict):
    email: Annotated[str, BeforeValidator(str.strip), Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)]
    role: OrgRole = "member"
    project_id: uuid.UUID | None = None
    project_role: ProjectRole | None = None


class TokenIn(_Strict):
    token: str = Field(min_length=10, max_length=200)


class OrgRoleIn(_Strict):
    role: OrgRole


class ProjectRoleIn(_Strict):
    role: ProjectRole


def _limit(request: Request, limiter_name: str, key: str) -> None:
    if not getattr(request.app.state, limiter_name).allow(key):
        raise AppError(429, "rate_limited", "Too many requests. Try again later.")


@router.get("/orgs/{organization_id}/members")
def list_members(organization_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return members.list_org(db, caller.user, organization_id)


@router.post("/orgs/{organization_id}/invitations", status_code=201)
def invite(organization_id: uuid.UUID, body: InviteIn, request: Request, caller: CsrfCaller, db: DbSession,
           settings: AppSettings) -> dict:
    members.require_org_admin(db, caller.user.id, organization_id)
    _limit(request, "invite_limiter", str(organization_id))
    invitation = members.invite(db, settings, caller.user, organization_id=organization_id, email=body.email,
                                role=body.role, project_id=body.project_id, project_role=body.project_role)
    return {"id": str(invitation.id), "email": invitation.email, "role": invitation.role,
            "project_role": invitation.project_role, "expires_at": invitation.expires_at.isoformat()}


@router.post("/orgs/{organization_id}/invitations/{invitation_id}/revoke")
def revoke(organization_id: uuid.UUID, invitation_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    members.revoke(db, caller.user, organization_id=organization_id, invitation_id=invitation_id)
    return {"status": "revoked"}


@router.post("/invitations/preview")
def preview(body: TokenIn, request: Request, db: DbSession) -> dict:
    ip = request.client.host if request.client else "unknown"
    _limit(request, "auth_limiter", f"invite-preview:{ip}")
    return members.preview(db, body.token)


@router.post("/invitations/accept")
def accept(body: TokenIn, request: Request, caller: CsrfCaller, db: DbSession) -> dict:
    _limit(request, "auth_limiter", f"invite-accept:{caller.user.id}")
    invitation = members.accept(db, caller.user, body.token)
    return {"organization_id": str(invitation.organization_id),
            "project_id": str(invitation.project_id) if invitation.project_id else None}


@router.put("/orgs/{organization_id}/members/{user_id}")
def set_org_role(organization_id: uuid.UUID, user_id: uuid.UUID, body: OrgRoleIn, caller: CsrfCaller,
                 db: DbSession) -> dict:
    members.set_org_role(db, caller.user, organization_id=organization_id, user_id=user_id, role=body.role)
    return {"user_id": str(user_id), "role": body.role}


@router.delete("/orgs/{organization_id}/members/{user_id}")
def remove_member(organization_id: uuid.UUID, user_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    members.remove_from_org(db, caller.user, organization_id=organization_id, user_id=user_id)
    return {"status": "removed"}


@router.get("/projects/{project_id}/members")
def project_members(project_id: uuid.UUID, caller: CurrentCaller, db: DbSession) -> dict:
    return {"items": members.list_project(db, caller.user, project_id)}


@router.put("/projects/{project_id}/members/{user_id}")
def set_project_role(project_id: uuid.UUID, user_id: uuid.UUID, body: ProjectRoleIn, caller: CsrfCaller,
                     db: DbSession) -> dict:
    members.set_project_role(db, caller.user, project_id=project_id, user_id=user_id, role=body.role)
    return {"user_id": str(user_id), "role": body.role}


@router.delete("/projects/{project_id}/members/{user_id}")
def remove_project_member(project_id: uuid.UUID, user_id: uuid.UUID, caller: CsrfCaller, db: DbSession) -> dict:
    members.remove_from_project(db, caller.user, project_id=project_id, user_id=user_id)
    return {"status": "removed"}
