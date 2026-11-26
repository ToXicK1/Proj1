"""A person's Home over HTTP: one read of what is waiting on them across their projects."""

from fastapi import APIRouter

from app.auth.deps import CurrentCaller, DbSession
from app.home import service

router = APIRouter(prefix="/api/v1/me", tags=["home"])


@router.get("/day")
def my_day(caller: CurrentCaller, db: DbSession) -> dict:
    return service.my_day(db, caller.user)
