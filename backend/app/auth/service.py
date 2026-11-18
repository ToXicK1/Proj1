"""Identity: self-signup with email verification, login with lockout, server-side sessions.

Every function that changes state appends audit events in the same transaction and commits.
Responses never reveal whether an email is registered (see signup).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import PLATFORM_CHAIN, append_event, org_chain
from app.auth.models import EmailToken, User, UserSession
from app.core.config import Settings
from app.core.db import uuid7
from app.core.errors import AppError
from app.core.security import (
    burn_password_time,
    hash_password,
    new_token,
    sha256_hex,
    verify_password,
)
from app.notifications.models import EmailOutbox
from app.organizations.models import Membership, Organization
from app.organizations.service import slugify

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_password(password: str, settings: Settings) -> None:
    if len(password) < settings.min_password_length:
        raise AppError(422, "weak_password", f"Password must be at least {settings.min_password_length} characters")
    if len(password) > settings.max_password_length:
        raise AppError(422, "weak_password", "Password is too long")


def _enqueue_email(db: Session, *, kind: str, recipient: str, subject: str, body: str) -> None:
    db.add(EmailOutbox(kind=kind, recipient=recipient, subject=subject, body=body))


def signup(db: Session, settings: Settings, *, email: str, password: str, display_name: str) -> None:
    """Start signup. Always returns normally so callers cannot learn which emails exist."""
    email = normalize_email(email)
    validate_password(password, settings)
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        burn_password_time(password)  # same work as a new signup, so timing does not reveal the email
        _enqueue_email(
            db,
            kind="signup_existing_account",
            recipient=email,
            subject="Your AI-DLC account",
            body="Someone tried to register this email address. If it was you, sign in instead.",
        )
        db.commit()
        return

    user = User(
        id=uuid7(),
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip(),
        status="pending_verification",
        failed_login_count=0,
    )
    raw = new_token()
    db.add(user)
    db.flush()  # user row first so the token's foreign key is satisfied
    db.add(
        EmailToken(
            id=uuid7(),
            user_id=user.id,
            purpose="verify_email",
            token_hash=sha256_hex(raw),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.email_token_ttl_hours),
        )
    )
    link = f"{settings.public_base_url}/verify-email?token={raw}"
    _enqueue_email(
        db,
        kind="verify_email",
        recipient=email,
        subject="Verify your AI-DLC email",
        body=f"Confirm your email address to finish creating your account:\n{link}\n",
    )
    append_event(
        db,
        chain_key=PLATFORM_CHAIN,
        event_type="auth.signup_requested",
        actor_type="human",
        actor_id=str(user.id),
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent signup with the same email won the race; respond as if it was normal.
        db.rollback()


def verify_email(db: Session, settings: Settings, *, token: str) -> User:
    """Consume a verification token, activate the user and create their personal organization."""
    now = datetime.now(UTC)
    row = db.execute(
        select(EmailToken).where(EmailToken.token_hash == sha256_hex(token)).with_for_update()
    ).scalar_one_or_none()
    if row is None or row.purpose != "verify_email" or row.consumed_at is not None or _expired(row.expires_at, now):
        raise AppError(400, "invalid_or_expired_token", "This verification link is invalid or has expired")

    user = db.execute(select(User).where(User.id == row.user_id).with_for_update()).scalar_one()
    if user.status != "pending_verification":
        raise AppError(400, "invalid_or_expired_token", "This verification link is invalid or has expired")

    row.consumed_at = now
    user.status = "active"
    user.verified_at = now
    user.updated_at = now

    org = Organization(
        id=uuid7(),
        name=f"{user.display_name}'s workspace"[:120],
        slug=slugify(user.display_name, suffix=uuid.uuid4().hex[:8]),
    )
    db.add(org)
    db.flush()  # organization row first so the membership's foreign key is satisfied
    db.add(Membership(id=uuid7(), organization_id=org.id, user_id=user.id, role="org_admin"))
    db.flush()

    append_event(
        db, chain_key=PLATFORM_CHAIN, event_type="auth.email_verified", actor_type="human", actor_id=str(user.id)
    )
    append_event(
        db,
        chain_key=org_chain(org.id),
        event_type="org.created",
        actor_type="human",
        actor_id=str(user.id),
        organization_id=org.id,
        payload={"reason": "personal_workspace"},
    )
    db.commit()
    return user


def _expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= now


def authenticate(db: Session, settings: Settings, *, email: str, password: str) -> User:
    email = normalize_email(email)
    now = datetime.now(UTC)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        burn_password_time(password)
        append_event(
            db,
            chain_key=PLATFORM_CHAIN,
            event_type="auth.login_failed",
            actor_type="human",
            payload={"reason": "unknown_account", "email_sha256": sha256_hex(email)},
        )
        db.commit()
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")

    if user.locked_until is not None and not _expired(user.locked_until, now):
        raise AppError(423, "account_locked", "Too many failed attempts. Try again later.")

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        reason = "bad_password"
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
            reason = "locked_after_failures"
        append_event(
            db,
            chain_key=PLATFORM_CHAIN,
            event_type="auth.login_failed",
            actor_type="human",
            actor_id=str(user.id),
            payload={"reason": reason},
        )
        db.commit()
        raise AppError(401, "invalid_credentials", "Email or password is incorrect")

    if user.status == "pending_verification":
        raise AppError(403, "email_not_verified", "Verify your email address before signing in")
    if user.status != "active":
        raise AppError(403, "account_unavailable", "This account is not available")

    user.failed_login_count = 0
    user.locked_until = None
    append_event(
        db, chain_key=PLATFORM_CHAIN, event_type="auth.login_succeeded", actor_type="human", actor_id=str(user.id)
    )
    db.commit()
    return user


def create_session(db: Session, settings: Settings, user: User) -> str:
    """Create a server-side session and return the raw token for the cookie (never stored)."""
    raw = new_token()
    now = datetime.now(UTC)
    db.add(
        UserSession(
            id=uuid7(),
            user_id=user.id,
            token_hash=sha256_hex(raw),
            created_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
        )
    )
    db.commit()
    return raw


def find_session(db: Session, raw_token: str) -> UserSession | None:
    """Return the live session for a raw cookie token, or None."""
    row = db.execute(
        select(UserSession).where(UserSession.token_hash == sha256_hex(raw_token))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or _expired(row.expires_at, datetime.now(UTC)):
        return None
    return row


def revoke_session(db: Session, raw_token: str, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    db.execute(
        update(UserSession)
        .where(UserSession.token_hash == sha256_hex(raw_token), UserSession.user_id == user_id)
        .values(revoked_at=now)
    )
    append_event(db, chain_key=PLATFORM_CHAIN, event_type="auth.logout", actor_type="human", actor_id=str(user_id))
    db.commit()
