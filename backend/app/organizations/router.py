from fastapi import APIRouter, Request

from app.auth.deps import CurrentCaller, DbSession
from app.organizations import service

router = APIRouter(prefix="/api/v1/orgs", tags=["organizations"])


@router.get("")
def list_my_orgs(caller: CurrentCaller, db: DbSession) -> dict:
    items = [
        {"id": str(org.id), "name": org.name, "slug": org.slug, "role": membership.role}
        for org, membership in service.memberships_for_user(db, caller.user.id)
    ]
    return {"items": items}


@router.get("/access")
def my_access(request: Request, caller: CurrentCaller, db: DbSession) -> dict:
    """Where this account stands, including a request still waiting for an administrator."""
    return service.access_for(db, caller.user.id, managed=request.app.state.settings.account_mode == "managed")
