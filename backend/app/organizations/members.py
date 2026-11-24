"""Organization members, email invitations and project roles.

Rules:
- only organization admins invite people or change roles
- an invitation works once, expires, and can be accepted only by the account with the invited email
- nobody changes their own role, so a person cannot make themselves a reviewer of their own work
- every project keeps at least one project owner
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.models import Profile
from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.auth.service import normalize_email
from app.core.config import Settings
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.core.security import new_token, sha256_hex
from app.notifications.models import EmailOutbox
from app.organizations.models import (
    ORG_ROLES,
    OVERSEER_ROLES,
    MemberProfile,
    Membership,
    Organization,
    OrganizationInvitation,
)
from app.organizations.service import membership_for, require_org_admin
from app.projects.models import PROJECT_ROLES, Project, ProjectMember


def _audit(db: Session, organization_id: uuid.UUID, event: str, actor: uuid.UUID, payload: dict,
           project_id: uuid.UUID | None = None) -> None:
    append_event(db, chain_key=org_chain(organization_id), event_type=event, actor_type="human",
                 actor_id=str(actor), organization_id=organization_id, project_id=project_id, payload=payload)


def _expired(moment: datetime) -> bool:
    return (moment if moment.tzinfo else moment.replace(tzinfo=UTC)) <= datetime.now(UTC)


def _org_project(db: Session, organization_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.organization_id != organization_id:
        raise not_found()
    return project


def invite(db: Session, settings: Settings, actor: User, *, organization_id: uuid.UUID, email: str, role: str,
           project_id: uuid.UUID | None, project_role: str | None) -> OrganizationInvitation:
    require_org_admin(db, actor.id, organization_id)
    email = normalize_email(email)
    if role not in ORG_ROLES:
        raise AppError(422, "invalid_role", "Unknown organization role")
    if (project_id is None) != (project_role is None):
        raise AppError(422, "invalid_project_role", "Give both a project and a project role, or neither")
    if project_role is not None and project_role not in PROJECT_ROLES:
        raise AppError(422, "invalid_project_role", "Unknown project role")
    project = _org_project(db, organization_id, project_id) if project_id else None
    existing_user = db.execute(select(User.id).where(User.email == email)).scalar_one_or_none()
    if existing_user and membership_for(db, existing_user, organization_id):
        raise AppError(409, "already_member", "This person is already in the organization")

    pending = db.execute(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == organization_id, OrganizationInvitation.email == email,
        OrganizationInvitation.status == "pending").with_for_update()).scalar_one_or_none()
    if pending is not None:
        if not _expired(pending.expires_at):
            raise AppError(409, "invitation_pending", "This person already has a pending invitation")
        pending.status = "expired"
        db.flush()

    raw = new_token()
    invitation = OrganizationInvitation(
        id=uuid7(), organization_id=organization_id, email=email, role=role,
        project_id=project.id if project else None, project_role=project_role, token_hash=sha256_hex(raw),
        status="pending", invited_by=actor.id,
        expires_at=datetime.now(UTC) + timedelta(days=settings.invite_ttl_days),
    )
    organization = db.get(Organization, organization_id)
    db.add(invitation)
    db.add(EmailOutbox(
        kind="org_invitation", recipient=email, subject="You are invited to an AI-DLC workspace",
        body=(f"{actor.display_name} invited you to join {organization.name}.\n"
              f"Open this link to accept:\n{settings.public_base_url}/accept-invite?token={raw}\n"),
    ))
    _audit(db, organization_id, "member.invited", actor.id,
           {"invitation": str(invitation.id), "email_sha256": sha256_hex(email), "role": role,
            "project_role": project_role}, project.id if project else None)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(409, "invitation_pending", "This person already has a pending invitation") from exc
    return invitation


def _usable(db: Session, token: str, *, lock: bool) -> OrganizationInvitation:
    query = select(OrganizationInvitation).where(OrganizationInvitation.token_hash == sha256_hex(token))
    invitation = db.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if invitation is None or invitation.status != "pending" or _expired(invitation.expires_at):
        raise AppError(400, "invalid_or_expired_invitation", "This invitation is invalid or has expired")
    return invitation


def _hint(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def preview(db: Session, token: str) -> dict:
    invitation = _usable(db, token, lock=False)
    project = db.get(Project, invitation.project_id) if invitation.project_id else None
    return {
        "organization": db.get(Organization, invitation.organization_id).name,
        "role": invitation.role,
        "project": project.name if project else None,
        "project_role": invitation.project_role,
        "email_hint": _hint(invitation.email),
    }


def accept(db: Session, user: User, token: str) -> OrganizationInvitation:
    try:
        invitation = _usable(db, token, lock=True)
        if invitation.email != user.email:
            raise AppError(403, "invitation_wrong_account", "This invitation was sent to a different email address")
        organization_id = invitation.organization_id
        if membership_for(db, user.id, organization_id) is None:
            db.add(Membership(id=uuid7(), organization_id=organization_id, user_id=user.id, role=invitation.role))
            db.flush()
        if invitation.project_id and _project_member(db, invitation.project_id, user.id) is None:
            db.add(ProjectMember(id=uuid7(), project_id=invitation.project_id, user_id=user.id,
                                 project_role=invitation.project_role))
        invitation.status = "accepted"
        invitation.accepted_by = user.id
        invitation.accepted_at = datetime.now(UTC)
        _audit(db, organization_id, "member.joined", user.id,
               {"invitation": str(invitation.id), "role": invitation.role, "project_role": invitation.project_role},
               invitation.project_id)
        db.commit()
        return invitation
    except Exception:
        db.rollback()
        raise


def revoke(db: Session, actor: User, *, organization_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
    require_org_admin(db, actor.id, organization_id)
    invitation = db.execute(select(OrganizationInvitation).where(OrganizationInvitation.id == invitation_id)
                            .with_for_update()).scalar_one_or_none()
    if invitation is None or invitation.organization_id != organization_id:
        raise not_found()
    if invitation.status != "pending":
        raise AppError(409, "invitation_closed", "This invitation is no longer pending")
    invitation.status = "revoked"
    _audit(db, organization_id, "member.invitation_revoked", actor.id, {"invitation": str(invitation.id)})
    db.commit()


def list_org(db: Session, actor: User, organization_id: uuid.UUID) -> dict:
    require_org_admin(db, actor.id, organization_id)
    members = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                         .where(Membership.organization_id == organization_id).order_by(User.display_name)).all()
    held: dict[uuid.UUID, list[str]] = {}
    for row in db.execute(select(MemberProfile).where(MemberProfile.organization_id == organization_id)).scalars():
        held.setdefault(row.user_id, []).append(row.profile_key)
    invites = db.execute(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == organization_id, OrganizationInvitation.status == "pending",
    ).order_by(OrganizationInvitation.created_at.desc())).scalars()
    return {
        "members": [{"user_id": str(u.id), "display_name": u.display_name, "email": u.email, "role": m.role,
                     "status": m.status, "requested_role": m.requested_role, "is_you": u.id == actor.id,
                     "profiles": sorted(held.get(u.id, []))} for m, u in members],
        "invitations": [{"id": str(i.id), "email": i.email, "role": i.role, "project_role": i.project_role,
                         "project_id": str(i.project_id) if i.project_id else None,
                         "expires_at": i.expires_at.isoformat()} for i in invites if not _expired(i.expires_at)],
    }


def sync_overseer(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID, previous: str, role: str) -> None:
    """Administrators and project managers see every project; losing that role takes the access away again."""
    projects = set(db.execute(select(Project.id).where(Project.organization_id == organization_id)).scalars())
    joined = set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user_id,
                                                                   ProjectMember.project_id.in_(projects))).scalars())
    if role in OVERSEER_ROLES:
        for project_id in sorted(projects - joined):
            db.add(ProjectMember(id=uuid7(), project_id=project_id, user_id=user_id, project_role="viewer"))
    elif previous in OVERSEER_ROLES:
        db.execute(delete(ProjectMember).where(ProjectMember.user_id == user_id, ProjectMember.project_role == "viewer",
                                               ProjectMember.project_id.in_(projects)))


def _not_self(actor: User, target: uuid.UUID) -> None:
    if actor.id == target:
        raise AppError(403, "cannot_change_own_role", "Another administrator must change your access")


def _membership(db: Session, organization_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    row = db.execute(select(Membership).where(Membership.organization_id == organization_id,
                                              Membership.user_id == user_id).with_for_update()).scalar_one_or_none()
    if row is None:
        raise not_found()
    return row


def set_org_role(db: Session, actor: User, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    require_org_admin(db, actor.id, organization_id)
    _not_self(actor, user_id)
    if role not in ORG_ROLES:
        raise AppError(422, "invalid_role", "Unknown organization role")
    row = _membership(db, organization_id, user_id)
    previous, row.role = row.role, role
    sync_overseer(db, organization_id, user_id, previous, role)
    _audit(db, organization_id, "member.role_changed", actor.id,
           {"user": str(user_id), "from": previous, "to": role})
    db.commit()


def set_access(db: Session, actor: User, *, organization_id: uuid.UUID, user_id: uuid.UUID, role: str,
               profiles: list[str]) -> None:
    """Confirms a person's organization role and professional profiles. Only another administrator can."""
    require_org_admin(db, actor.id, organization_id)
    _not_self(actor, user_id)
    if role not in ORG_ROLES:
        raise AppError(422, "invalid_role", "Unknown organization role")
    known = set(db.execute(select(Profile.key).where(Profile.organization_id == organization_id)).scalars())
    if not set(profiles) <= known:
        raise AppError(422, "unknown_profile", "Choose profiles that exist in this organization")
    try:
        row = _membership(db, organization_id, user_id)
        previous = sorted(db.execute(select(MemberProfile.profile_key).where(
            MemberProfile.organization_id == organization_id, MemberProfile.user_id == user_id)).scalars())
        previous_role = row.role
        row.role, row.status = role, "active"
        sync_overseer(db, organization_id, user_id, previous_role, role)
        db.execute(delete(MemberProfile).where(MemberProfile.organization_id == organization_id,
                                               MemberProfile.user_id == user_id))
        for key in sorted(set(profiles)):
            db.add(MemberProfile(id=uuid7(), organization_id=organization_id, user_id=user_id, profile_key=key,
                                 confirmed_by=actor.id))
        if set(profiles) - {"project_manager"}:
            joined = set(db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)).scalars())
            for project_id in db.execute(select(Project.id).where(Project.organization_id == organization_id)).scalars():
                if project_id not in joined:
                    db.add(ProjectMember(id=uuid7(), project_id=project_id, user_id=user_id,
                                         project_role="team_member"))
        _audit(db, organization_id, "member.access_confirmed", actor.id,
               {"user": str(user_id), "role": role, "profiles": sorted(set(profiles)), "previous": previous})
        db.commit()
    except Exception:
        db.rollback()
        raise


def _project_member(db: Session, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember | None:
    return db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id,
                                                  ProjectMember.user_id == user_id)).scalar_one_or_none()


def _lock_project(db: Session, project_id: uuid.UUID) -> Project | None:
    return db.execute(select(Project).where(Project.id == project_id).with_for_update()).scalar_one_or_none()


def _assert_other_owner(db: Session, project: Project, leaving: uuid.UUID) -> None:
    others = db.execute(select(ProjectMember.id).where(
        ProjectMember.project_id == project.id, ProjectMember.project_role == "project_owner",
        ProjectMember.user_id != leaving)).first()
    if others is None:
        raise AppError(409, "last_project_owner", f"Project '{project.name}' needs another owner first")


def remove_from_org(db: Session, actor: User, *, organization_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Removes the person and all their project access in this organization, or nothing."""
    require_org_admin(db, actor.id, organization_id)
    _not_self(actor, user_id)
    try:
        row = _membership(db, organization_id, user_id)
        project_ids = list(db.execute(select(Project.id).where(Project.organization_id == organization_id)
                                      .order_by(Project.id).with_for_update()).scalars())
        if project_ids:
            for member in db.execute(select(ProjectMember).where(
                    ProjectMember.user_id == user_id, ProjectMember.project_id.in_(project_ids))).scalars().all():
                if member.project_role == "project_owner":
                    _assert_other_owner(db, db.get(Project, member.project_id), user_id)
            db.execute(delete(ProjectMember).where(ProjectMember.user_id == user_id,
                                                   ProjectMember.project_id.in_(project_ids)))
        db.execute(delete(MemberProfile).where(MemberProfile.organization_id == organization_id,
                                               MemberProfile.user_id == user_id))
        db.delete(row)
        _audit(db, organization_id, "member.removed", actor.id, {"user": str(user_id)})
        db.commit()
    except Exception:
        db.rollback()
        raise


def _project_for_admin(db: Session, actor: User, project_id: uuid.UUID) -> Project:
    project = _lock_project(db, project_id)
    if project is None:
        raise not_found()
    require_org_admin(db, actor.id, project.organization_id)
    return project


def set_project_role(db: Session, actor: User, *, project_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    try:
        project = _project_for_admin(db, actor, project_id)
        _not_self(actor, user_id)
        if role not in PROJECT_ROLES:
            raise AppError(422, "invalid_project_role", "Unknown project role")
        if membership_for(db, user_id, project.organization_id) is None:
            raise not_found()
        row = _project_member(db, project.id, user_id)
        previous = row.project_role if row else None
        if previous == "project_owner" and role != "project_owner":
            _assert_other_owner(db, project, user_id)
        if row is None:
            db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=user_id, project_role=role))
        else:
            row.project_role = role
        _audit(db, project.organization_id, "project_member.role_set", actor.id,
               {"user": str(user_id), "from": previous, "to": role}, project.id)
        db.commit()
    except Exception:
        db.rollback()
        raise


def remove_from_project(db: Session, actor: User, *, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    try:
        project = _project_for_admin(db, actor, project_id)
        _not_self(actor, user_id)
        row = _project_member(db, project.id, user_id)
        if row is None:
            raise not_found()
        if row.project_role == "project_owner":
            _assert_other_owner(db, project, user_id)
        db.delete(row)
        _audit(db, project.organization_id, "project_member.removed", actor.id, {"user": str(user_id)}, project.id)
        db.commit()
    except Exception:
        db.rollback()
        raise


def list_project(db: Session, viewer: User, project_id: uuid.UUID) -> list[dict]:
    if _project_member(db, project_id, viewer.id) is None:
        project = db.get(Project, project_id)
        if project is None or membership_for(db, viewer.id, project.organization_id) is None \
                or membership_for(db, viewer.id, project.organization_id).role != "org_admin":
            raise not_found()
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id)
                      .where(ProjectMember.project_id == project_id).order_by(User.display_name)).all()
    return [{"user_id": str(u.id), "display_name": u.display_name, "role": m.project_role} for m, u in rows]
