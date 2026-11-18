from fastapi import APIRouter

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
