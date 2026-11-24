"""Project creation and project-scoped access.

Access rule: a user sees a project only through a ProjectMember row. Administrators and project managers
are given a viewer row on every project of their organization; nobody else is implicitly a member. Anything the caller may not see returns not_found, never forbidden, so the
existence of other tenants' projects cannot be probed.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.hooks import service as hooks
from app.organizations.models import OVERSEER_ROLES, MemberProfile, Membership
from app.organizations.service import membership_for
from app.projects.models import Project, ProjectMember

MAX_NAME = 120
MAX_DESCRIPTION = 2000
MAX_TYPE = 64


def create_project(
    db: Session,
    user: User,
    *,
    organization_id: uuid.UUID,
    name: str,
    description: str,
    project_type: str,
    owner_user_id: uuid.UUID | None = None,
    managed: bool = False,
) -> Project:
    # Users who are not members of the organization get not_found, not forbidden.
    membership = membership_for(db, user.id, organization_id)
    if membership is None:
        raise not_found()
    if managed and membership.role != "org_admin":
        raise AppError(403, "not_permitted", "Only administrators create projects")
    if membership.role == "member":
        raise AppError(403, "not_permitted", "Only project owners can create projects")
    owner = user
    if owner_user_id is not None:  # an administrator creates the project for a client
        if membership.role != "org_admin":
            raise AppError(403, "not_permitted", "Only administrators create projects for someone else")
        client = membership_for(db, owner_user_id, organization_id)
        if client is None or client.role != "project_owner" or client.status != "active":
            raise AppError(422, "invalid_owner", "Choose a client of this organization as the project owner")
        owner = db.get(User, owner_user_id)
    elif managed:
        raise AppError(422, "owner_required", "Choose the client who owns this project")

    name = name.strip()
    project_type = project_type.strip()
    if not name or len(name) > MAX_NAME:
        raise AppError(422, "invalid_name", f"Project name must be 1-{MAX_NAME} characters")
    if len(description) > MAX_DESCRIPTION:
        raise AppError(422, "invalid_description", f"Description must be at most {MAX_DESCRIPTION} characters")
    if not project_type or len(project_type) > MAX_TYPE:
        raise AppError(422, "invalid_project_type", f"Project type must be 1-{MAX_TYPE} characters")

    project = Project(
        id=uuid7(),
        organization_id=organization_id,
        name=name,
        description=description,
        project_type=project_type,
        status="active",
        created_by=user.id,
    )
    db.add(project)
    db.flush()  # project row first so the membership's foreign key is satisfied
    db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=owner.id, project_role="project_owner"))
    holders = set(db.execute(select(MemberProfile.user_id).where(
        MemberProfile.organization_id == organization_id)).scalars()) - {owner.id}
    for holder in holders:  # the people who hold a profile work on every project of the organization
        db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=holder, project_role="team_member"))
    overseers = set(db.execute(select(Membership.user_id).where(
        Membership.organization_id == organization_id, Membership.status == "active",
        Membership.role.in_(OVERSEER_ROLES))).scalars()) - holders - {owner.id}
    for person in overseers:  # administrators and project managers see every project
        db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=person, project_role="viewer"))
    db.flush()
    append_event(
        db,
        chain_key=org_chain(organization_id),
        event_type="project.created",
        actor_type="human",
        actor_id=str(user.id),
        organization_id=organization_id,
        project_id=project.id,
        payload={"project_type": project_type},
    )
    hooks.run_hooks(db, hooks.HookScope(organization_id, project.id, project.project_type), "project.created")
    db.commit()
    return project


def projects_for_user(db: Session, user_id: uuid.UUID) -> list[Project]:
    return list(
        db.execute(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        ).scalars()
    )


def project_for_user(db: Session, user_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(Project.id == project_id, ProjectMember.user_id == user_id)
    ).scalar_one_or_none()
    if project is None:
        raise not_found()
    return project
