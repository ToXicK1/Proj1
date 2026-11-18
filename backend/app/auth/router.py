from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.auth import service
from app.auth.deps import AppSettings, CsrfCaller, CurrentCaller, DbSession
from app.core.errors import AppError
from app.core.ratelimit import SlidingWindowLimiter
from app.core.security import csrf_for_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignupIn(_Strict):
    email: Annotated[str, BeforeValidator(str.strip), Field(min_length=3, max_length=254, pattern=service.EMAIL_PATTERN)]
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class VerifyIn(_Strict):
    token: str = Field(min_length=10, max_length=200)


class LoginIn(_Strict):
    email: Annotated[str, BeforeValidator(str.strip), Field(min_length=3, max_length=254)]
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str


def _user_out(user) -> UserOut:  # type: ignore[no-untyped-def]
    return UserOut(id=str(user.id), email=user.email, display_name=user.display_name)


def _limit(request: Request, limiter: SlidingWindowLimiter, scope: str) -> None:
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"{scope}:{ip}"):
        raise AppError(429, "rate_limited", "Too many requests. Try again shortly.")


@router.post("/signup", status_code=202)
def signup(body: SignupIn, request: Request, db: DbSession, settings: AppSettings) -> dict[str, str]:
    _limit(request, request.app.state.auth_limiter, "signup")
    service.signup(db, settings, email=body.email, password=body.password, display_name=body.display_name)
    return {"status": "check_email"}


@router.post("/verify-email")
def verify_email(body: VerifyIn, request: Request, db: DbSession, settings: AppSettings) -> dict[str, str]:
    _limit(request, request.app.state.auth_limiter, "verify")
    user = service.verify_email(db, settings, token=body.token)
    return {"status": "verified", "email": user.email}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession, settings: AppSettings) -> dict:
    _limit(request, request.app.state.auth_limiter, "login")
    user = service.authenticate(db, settings, email=body.email, password=body.password)
    raw = service.create_session(db, settings, user)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"user": _user_out(user).model_dump(), "csrf_token": csrf_for_session(settings.secret_key, raw)}


@router.get("/me")
def me(caller: CurrentCaller) -> dict:
    return {"user": _user_out(caller.user).model_dump(), "csrf_token": caller.csrf_token}


@router.post("/logout")
def logout(caller: CsrfCaller, response: Response, db: DbSession, settings: AppSettings) -> dict[str, str]:
    service.revoke_session(db, caller.raw_token, caller.user.id)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"status": "signed_out"}
