import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.organizations.models import Membership, Organization


def slugify(value: str, suffix: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:100] or "workspace"
    return f"{base}-{suffix}"


def memberships_for_user(db: Session, user_id: uuid.UUID) -> list[tuple[Organization, Membership]]:
    rows = db.execute(
        select(Organization, Membership)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.name)
    ).all()
    return [(org, m) for org, m in rows]


def membership_for(db: Session, user_id: uuid.UUID, organization_id: uuid.UUID) -> Membership | None:
    return db.execute(
        select(Membership).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id
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
