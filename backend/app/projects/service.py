"""Project creation and project-scoped access.

Access rule: a user sees a project only through a ProjectMember row. Organization admins are not
implicitly members. Anything the caller may not see returns not_found, never forbidden, so the
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
) -> Project:
    # Users who are not members of the organization get not_found, not forbidden.
    if membership_for(db, user.id, organization_id) is None:
        raise not_found()

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
    db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=user.id, project_role="project_owner"))
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
