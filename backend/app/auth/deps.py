from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.models import User
from app.core.config import Settings, get_settings
from app.core.db import iter_session
from app.core.errors import AppError
from app.core.security import constant_time_equal, csrf_for_session

CSRF_HEADER = "X-CSRF-Token"
# All a person may do while their administrator-issued temporary password is still in use.
PASSWORD_CHANGE_PATHS = frozenset({"/api/v1/auth/me", "/api/v1/auth/logout", "/api/v1/auth/password"})


def get_db(request: Request):  # type: ignore[no-untyped-def]
    yield from iter_session(request.app.state.session_factory)


DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class Caller:
    user: User
    raw_token: str
    csrf_token: str


def current_caller(request: Request, db: DbSession, settings: AppSettings) -> Caller:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise AppError(401, "unauthenticated", "Sign in required")
    session_row = service.find_session(db, raw)
    if session_row is None:
        raise AppError(401, "unauthenticated", "Sign in required")
    user = db.get(User, session_row.user_id)
    if user is None or user.status != "active":
        raise AppError(401, "unauthenticated", "Sign in required")
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise AppError(403, "password_change_required", "Choose your own password before continuing")
    return Caller(user=user, raw_token=raw, csrf_token=csrf_for_session(settings.secret_key, raw))


CurrentCaller = Annotated[Caller, Depends(current_caller)]


def require_csrf(request: Request, caller: CurrentCaller, settings: AppSettings) -> Caller:
    """Mutating endpoints call this. The token is derived from the session, so forged cross-site
    requests cannot know it."""
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not constant_time_equal(sent, caller.csrf_token):
        raise AppError(403, "csrf_failed", "Missing or invalid CSRF token")
    return caller


CsrfCaller = Annotated[Caller, Depends(require_csrf)]

