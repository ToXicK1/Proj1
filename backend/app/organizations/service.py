import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.organizations.models import MemberProfile, Membership, Organization


def slugify(value: str, suffix: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:100] or "workspace"
    return f"{base}-{suffix}"


def memberships_for_user(db: Session, user_id: uuid.UUID) -> list[tuple[Organization, Membership]]:
    rows = db.execute(
        select(Organization, Membership)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id, Membership.status == "active")
        .order_by(Organization.name)
    ).all()
    return [(org, m) for org, m in rows]


def membership_for(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> Membership | None:
    return db.execute(
        select(Membership).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id,
            Membership.status == "active",
        )
    ).scalar_one_or_none()


def require_org_admin(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Non-members get not_found. Members who are not org admins get not_permitted."""
    from app.core.errors import AppError, not_found

    membership = membership_for(db, user_id, organization_id)
    if membership is None:
        raise not_found()
    if membership.role != "org_admin":
        raise AppError(403, "not_permitted", "Only organization administrators can do this")


def access_for(db: Session, user_id: uuid.UUID, managed: bool = False) -> dict:
    rows = db.execute(select(Organization, Membership).join(Membership).where(Membership.user_id == user_id)).all()
    profiles = list(db.execute(select(MemberProfile.profile_key).where(MemberProfile.user_id == user_id)).scalars())
    active = [m for _, m in rows if m.status == "active"]
    pending = next(((o, m) for o, m in rows if m.status == "pending"), None)
    return {
        "status": "active" if active else "pending" if pending else "none",
        "is_admin": any(m.role == "org_admin" for m in active),
        "is_manager": any(m.role == "project_manager" for m in active),
        "oversees": any(m.role in ("org_admin", "project_manager") for m in active),
        # Managed accounts (RD-22): only administrators create projects, for a client they choose.
        "can_create_projects": any(m.role in (("org_admin",) if managed else ("org_admin", "project_owner"))
                                   for m in active),
        "account_mode": "managed" if managed else "self_service",
        "profiles": sorted(profiles),
        "requested_role": pending[1].requested_role if pending else None,
        "organization": pending[0].name if pending else None,
    }
