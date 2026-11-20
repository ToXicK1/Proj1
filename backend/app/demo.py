"""Local demo: one account per role in the shared organization, and a demo project on the real lifecycle.

For local development only. Run inside the API container:

    DEMO_PASSWORD=... python -m app.demo            # accounts and the demo project
    DEMO_PASSWORD=... python -m app.demo --no-run   # accounts only

The password comes from the environment and is never printed. Safe to repeat: existing demo accounts keep their
roles and get the given password; the demo project is created once.
"""

import os
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app import models  # noqa: F401  (registers every table)
from app.auth.models import User
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory, uuid7
from app.core.security import hash_password
from app.organizations.members import sync_overseer
from app.organizations.models import MemberProfile, Membership, Organization
from app.portal import service as portal
from app.projects.models import Project, ProjectMember
from app.projects.service import create_project

DOMAIN = "aidlc.test"  # reserved test domain: these addresses can never receive real mail
OWNER = ("demo.owner", "Olivia Owner (demo)", "project_owner", [])
PROFESSIONALS = [
    ("demo.analyst", "Asha Analyst (demo)", "business_analyst"),
    ("demo.architect", "Arjun Architect (demo)", "solution_architect"),
    ("demo.designer", "Dana Designer (demo)", "ui_ux_designer"),
    ("demo.developer", "Dev Developer (demo)", "software_developer"),
    ("demo.qa", "Quinn QA (demo)", "qa_security"),
    ("demo.devops", "Opal DevOps (demo)", "devops_release"),
]
# Administrators and project managers oversee every project; only the project manager is in the team chat.
OVERSEERS = [
    ("demo.admin", "Ada Admin (demo)", "org_admin"),
    ("demo.pm", "Pam Manager (demo)", "project_manager"),
]
PROJECT_NAME = "Demo: Recruiting portal"


def _account(db, org: Organization, admin: User, handle: str, name: str, role: str, profiles: list[str],
             password: str) -> User:
    email = f"{handle}@{DOMAIN}"
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = User(id=uuid7(), email=email, display_name=name, requested_role=role, status="active",
                    failed_login_count=0, verified_at=now, password_hash=hash_password(password))
        db.add(user)
        db.flush()
    else:
        user.password_hash, user.status, user.failed_login_count, user.locked_until = \
            hash_password(password), "active", 0, None
    membership = db.execute(select(Membership).where(Membership.organization_id == org.id,
                                                     Membership.user_id == user.id)).scalar_one_or_none()
    org_role = role if role in ("project_owner", "project_manager", "org_admin") else "member"
    if membership is None:
        db.add(Membership(id=uuid7(), organization_id=org.id, user_id=user.id, role=org_role, status="active",
                          requested_role=role))
    else:
        membership.status, membership.role = "active", org_role
    held = set(db.execute(select(MemberProfile.profile_key).where(
        MemberProfile.organization_id == org.id, MemberProfile.user_id == user.id)).scalars())
    for key in set(profiles) - held:
        db.add(MemberProfile(id=uuid7(), organization_id=org.id, user_id=user.id, profile_key=key,
                             confirmed_by=admin.id))
    db.commit()
    return user


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 12:
        sys.exit("Set DEMO_PASSWORD (at least 12 characters).")
    settings = get_settings()
    if settings.app_env == "production":
        sys.exit("Demo accounts are not created in production.")
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        org = db.execute(select(Organization).where(Organization.is_default.is_(True))).scalar_one_or_none()
        if org is None:
            sys.exit("No shared organization yet. Sign up the first account, then run this again.")
        admin = db.execute(select(User).join(Membership, Membership.user_id == User.id).where(
            Membership.organization_id == org.id, Membership.role == "org_admin",
            Membership.status == "active").order_by(Membership.created_at)).scalars().first()
        owner = _account(db, org, admin, *OWNER[:3], OWNER[3], password)
        people = [_account(db, org, admin, h, n, k, [k], password) for h, n, k in PROFESSIONALS]
        overseers = [(_account(db, org, admin, h, n, r, [], password), r) for h, n, r in OVERSEERS]
        print(f"Accounts ready: {1 + len(people) + len(overseers)} (password from DEMO_PASSWORD)")

        project = db.execute(select(Project).where(Project.organization_id == org.id,
                                                   Project.name == PROJECT_NAME)).scalar_one_or_none()
        if project is None:
            project = create_project(db, owner, organization_id=org.id, name=PROJECT_NAME,
                                     description="A portal where companies post jobs and review candidates. "
                                                 "Created by the local demo setup.",
                                     project_type="Web Application")
        joined = set(db.execute(select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)).scalars())
        for person in people:  # holders confirmed after the project existed still need to be on it
            if person.id not in joined:
                db.add(ProjectMember(id=uuid7(), project_id=project.id, user_id=person.id, project_role="team_member"))
        for person, role in overseers:  # they see every project in the organization
            sync_overseer(db, org.id, person.id, "", role)
        db.commit()
        print(f"Demo project: {project.id}")
        if "--no-run" in sys.argv or portal._execution(db, project.id) is not None:
            return
        for field, answer in (("problem", "Hiring takes too long and good candidates are missed."),
                              ("users", "Recruiters at small companies, and the candidates who apply."),
                              ("core_features", "Post jobs, receive applications, shortlist and message candidates.")):
            portal.answer_intake(db, owner, project.id, field, "answer", answer)
        revision = portal.get_intake(db, owner, project.id)["revision"]
        execution = portal.confirm_intake(db, owner, project.id, revision, [], "poc")
        execution_id = execution.id
    print("Queuing the lifecycle. The worker runs it on the configured AI model until the first approval is needed;")
    print("watch it in the project's AI activity menu.")
    portal.drive(factory, settings, None, uuid.UUID(str(execution_id)))


if __name__ == "__main__":
    main()
