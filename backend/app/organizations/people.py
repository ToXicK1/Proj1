"""Accounts created by an administrator (RD-22, P0).

The administrator adds each person with one of the platform's roles (and department profiles). The platform
generates a temporary password, returns it to the administrator exactly once to pass on, and stores only its hash.
The person must replace it at first sign-in; until then every other action is refused (app/auth/deps.py). A
temporary password expires after `temp_password_days`. The administrator can reset a password, which issues a new
temporary one and ends the person's sessions. Passwords are never logged or written to the audit chain.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User, UserSession
from app.auth.service import EMAIL_PATTERN, normalize_email
from app.core.config import Settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.core.security import hash_password
from app.organizations import members
from app.organizations.models import ORG_ROLES, Membership
from app.organizations.service import require_org_admin

# No look-alike characters (0/O, 1/l/I), so a password read aloud or copied by hand is not mistyped.
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def temporary_password() -> str:
    """Four groups of five: about 117 bits of entropy."""
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(20))
    return "-".join(raw[i:i + 5] for i in range(0, 20, 5))


def _issue(user: User, settings: Settings) -> str:
    temp = temporary_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.temp_password_expires_at = datetime.now(UTC) + timedelta(days=settings.temp_password_days)
    user.failed_login_count, user.locked_until = 0, None
    user.updated_at = datetime.now(UTC)
    return temp


def _audit(db: Session, organization_id: uuid.UUID, event: str, actor: User, payload: dict[str, Any]) -> None:
    append_event(db, chain_key=org_chain(organization_id), event_type=event, actor_type="human",
                 actor_id=str(actor.id), organization_id=organization_id, payload=payload)


def create_person(db: Session, settings: Settings, actor: User, *, organization_id: uuid.UUID, email: str,
                  display_name: str, role: str, profiles: list[str]) -> tuple[User, str]:
    """Returns the new account and its temporary password, which is never available again."""
    import re

    require_org_admin(db, actor.id, organization_id)
    email = normalize_email(email)
    if not re.fullmatch(EMAIL_PATTERN, email):
        raise AppError(422, "invalid_email", "Enter a valid email address")
    if not display_name.strip():
        raise AppError(422, "invalid_name", "Enter the person's name")
    if role not in ORG_ROLES:
        raise AppError(422, "invalid_role", "Unknown role")
    if db.execute(select(User.id).where(User.email == email)).first():
        raise AppError(409, "email_in_use", "An account with this email already exists")
    now = datetime.now(UTC)
    user = User(id=uuid7(), email=email, password_hash="!", display_name=display_name.strip()[:120],
                requested_role=role, status="active", verified_at=now)  # the administrator vouches for it
    temp = _issue(user, settings)
    db.add(user)
    db.flush()
    db.add(Membership(id=uuid7(), organization_id=organization_id, user_id=user.id, role="member",
                      status="active"))
    _audit(db, organization_id, "member.created", actor, {"user": str(user.id), "role": role,
                                                           "profiles": sorted(set(profiles))})
    db.commit()
    # Role, profiles and project access through the one existing path, so the rules stay in one place.
    members.set_access(db, actor, organization_id=organization_id, user_id=user.id, role=role, profiles=profiles)
    db.refresh(user)
    return user, temp


def reset_password(db: Session, settings: Settings, actor: User, *, organization_id: uuid.UUID,
                   user_id: uuid.UUID) -> str:
    """A new temporary password; the person's sessions end. Another administrator resets an administrator's own."""
    require_org_admin(db, actor.id, organization_id)
    if actor.id == user_id:
        raise AppError(403, "cannot_reset_self", "Change your own password from your account instead")
    if db.execute(select(Membership.id).where(Membership.organization_id == organization_id,
                                              Membership.user_id == user_id)).first() is None:
        raise not_found()
    user = db.get(User, user_id)
    temp = _issue(user, settings)
    db.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
               .values(revoked_at=datetime.now(UTC)))
    _audit(db, organization_id, "member.password_reset", actor, {"user": str(user.id)})
    db.commit()
    return temp


def create_first_admin(db: Session, settings: Settings, *, email: str, display_name: str,
                       organization_name: str) -> str:
    """The installation's first administrator, from the command line (python -m app.cli create-admin)."""
    from app.organizations.models import Organization

    email = normalize_email(email)
    if db.execute(select(User.id).where(User.email == email)).first():
        raise AppError(409, "email_in_use", "An account with this email already exists")
    now = datetime.now(UTC)
    user = User(id=uuid7(), email=email, password_hash="!", display_name=display_name.strip()[:120],
                requested_role="org_admin", status="active", verified_at=now)
    temp = _issue(user, settings)
    db.add(user)
    org = db.execute(select(Organization).where(Organization.is_default.is_(True))).scalar_one_or_none()
    if org is None:
        from app.organizations.service import slugify

        org = Organization(id=uuid7(), name=organization_name.strip()[:120] or "Organization", is_default=True,
                           slug=slugify(organization_name or "organization", suffix=uuid.uuid4().hex[:8]))
        db.add(org)
    db.flush()
    db.add(Membership(id=uuid7(), organization_id=org.id, user_id=user.id, role="org_admin", status="active"))
    append_event(db, chain_key=org_chain(org.id), event_type="member.created", actor_type="system",
                 organization_id=org.id, payload={"user": str(user.id), "role": "org_admin", "via": "command line"})
    db.commit()
    return temp
