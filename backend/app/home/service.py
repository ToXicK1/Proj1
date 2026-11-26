"""A person's Home: what is waiting on them today, across every project they are on (the Home + Workspace split).

Home is for information and to-dos: change sets to review, department packages to decide, tickets, messages that
name the person, unread notifications, and what the AI finished recently. The work itself happens in the Workspace.
Stage approvals keep their own endpoint (portal.service.my_reviews), which the Home page shows alongside.

Every item is read with the same access rules as its own page: a person only ever sees what they could open there.
Nothing here changes anything.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.core.errors import AppError

RECENT = timedelta(days=7)
AI_RECENT = timedelta(days=3)
LIMIT = 20
ENGINEERING_PROFILES = ("business_analyst", "solution_architect", "ui_ux_designer", "software_developer",
                        "qa_security", "devops_release")


def _projects(db: Session, user: User) -> list[tuple[Any, Any]]:
    """The person's projects with their scope there (owner, admin, manager, professional, member)."""
    from app.collab.service import scope_for
    from app.projects.service import projects_for_user

    out = []
    for project in projects_for_user(db, user.id):
        try:
            _, scope = scope_for(db, user, project.id)
        except AppError:
            continue
        out.append((project, scope))
    return out


def _engineer(scope: Any) -> bool:
    return scope.kind == "professional" and bool(scope.profiles & set(ENGINEERING_PROFILES))


def _change_sets(db: Session, user: User, projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """Change sets the person could review: open for review, not theirs, and not work they asked the AI for."""
    from app.devai.models import DeveloperAiRun
    from app.repos.models import ChangeSet

    ids = {p.id: p for p, s in projects if _engineer(s)}
    if not ids:
        return []
    rows = db.execute(select(ChangeSet).where(ChangeSet.project_id.in_(ids), ChangeSet.status.in_(
        ("in_review", "open"))).order_by(ChangeSet.created_at.desc()).limit(LIMIT * 2)).scalars().all()
    asked = {r.change_set_id: r for r in db.execute(select(DeveloperAiRun).where(
        DeveloperAiRun.change_set_id.in_([c.id for c in rows]))).scalars()} if rows else {}
    out = []
    for cs in rows:
        run = asked.get(cs.id)
        if cs.author_user_id == user.id or (run is not None and run.requested_by_user_id == user.id):
            continue
        out.append({"project_id": str(cs.project_id), "project": ids[cs.project_id].name, "id": str(cs.id),
                    "number": cs.number, "title": cs.title, "branch": cs.branch, "by_ai": run is not None,
                    "created_at": cs.created_at.isoformat() if cs.created_at else None})
    return out[:LIMIT]


def _packages(db: Session, user: User, projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """Department packages submitted for a decision in a department the person holds, by someone else."""
    from app.collab.service import holders
    from app.work.models import WorkPackage

    out = []
    for project, scope in projects:
        if scope.kind != "professional":
            continue
        rows = db.execute(select(WorkPackage).where(WorkPackage.project_id == project.id,
                                                    WorkPackage.status == "submitted")).scalars()
        for pkg in rows:
            if pkg.submitted_by_user_id == user.id or user.id not in holders(db, project, pkg.department):
                continue
            out.append({"project_id": str(project.id), "project": project.name, "id": str(pkg.id),
                        "department": pkg.department, "number": pkg.number, "title": pkg.title,
                        "submitted_at": pkg.submitted_at.isoformat() if pkg.submitted_at else None})
    return out[:LIMIT]


def _tickets(db: Session, user: User, projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """Open tickets assigned to the person, or unassigned in one of their departments."""
    from app.collab.models import Ticket

    out = []
    for project, scope in projects:
        if not scope.internal:
            continue
        rows = db.execute(select(Ticket).where(Ticket.project_id == project.id, Ticket.status.in_(
            ("open", "awaiting_professional"))).order_by(Ticket.number.desc())).scalars()
        for t in rows:
            mine = t.assignee_user_id == user.id
            if not mine and not (t.assignee_user_id is None and t.profile_key in scope.profiles):
                continue
            out.append({"project_id": str(project.id), "project": project.name, "id": str(t.id), "number": t.number,
                        "title": t.title, "kind": t.kind, "department": t.profile_key, "status": t.status,
                        "assigned_to_me": mine})
    return out[:LIMIT]


def _messages(db: Session, user: User, projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """The last week's team messages that name the person or were sent to them."""
    from app.collab.models import TeamMessage
    from app.work.service import _names

    since = datetime.now(UTC) - RECENT
    names_by_project = {p.id: p.name for p, s in projects if s.chat}
    rows = db.execute(select(TeamMessage).where(TeamMessage.created_at >= since, TeamMessage.author_user_id != user.id)
                      .where((TeamMessage.recipient_user_id == user.id)
                             | TeamMessage.mentions.contains([str(user.id)]))
                      .order_by(TeamMessage.created_at.desc()).limit(LIMIT * 2)).scalars().all()
    rows = [m for m in rows if m.project_id is None or m.project_id in names_by_project]
    authors = _names(db, {m.author_user_id for m in rows})
    return [{"id": str(m.id), "project_id": str(m.project_id) if m.project_id else None,
             "project": names_by_project.get(m.project_id) if m.project_id else None, "channel": m.channel,
             "author": authors.get(m.author_user_id, "AI team" if m.author_type == "ai" else "System"),
             "direct": m.recipient_user_id == user.id, "body": m.body[:240], "created_at": m.created_at.isoformat()}
            for m in rows][:LIMIT]


def _notifications(db: Session, user: User) -> dict[str, Any]:
    from app.notifications.models import Notification

    unread = db.execute(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                        .order_by(Notification.created_at.desc())).scalars().all()
    return {"unread": len(unread), "latest": [{"id": str(n.id), "kind": n.kind, "message": n.message,
                                              "project_id": str(n.project_id) if n.project_id else None,
                                              "created_at": n.created_at.isoformat()} for n in unread[:5]]}


def _ai_updates(db: Session, projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """What the AI finished in the last three days on projects where the person sees the professional view."""
    from app.events.service import WorkspaceEvent

    ids = {p.id: p.name for p, s in projects if s.internal}
    if not ids:
        return []
    since = datetime.now(UTC) - AI_RECENT
    rows = db.execute(select(WorkspaceEvent).where(WorkspaceEvent.project_id.in_(ids),
                                                   WorkspaceEvent.created_at >= since,
                                                   WorkspaceEvent.kind.in_(("developer_ai.finished",)))
                      .order_by(WorkspaceEvent.id.desc()).limit(LIMIT)).scalars()
    return [{"project_id": str(e.project_id), "project": ids[e.project_id], "kind": e.kind, "subject": e.subject,
             "data": e.data, "created_at": e.created_at.isoformat()} for e in rows]


def workspaces(projects: list[tuple[Any, Any]]) -> list[dict[str, Any]]:
    """Which workspaces the person can open: their own departments; the Project Manager, who coordinates them, every
    one. Administrators none: they oversee from the project overview (no role's workspace is theirs)."""
    out = []
    for project, scope in projects:
        if scope.kind == "manager":
            profiles = ["project_manager", *ENGINEERING_PROFILES]
        elif scope.kind == "professional":
            profiles = [p for p in ("project_manager", *ENGINEERING_PROFILES) if p in scope.profiles]
        else:
            continue
        if profiles:
            out.append({"project_id": str(project.id), "project": project.name, "profiles": profiles})
    return out


def my_day(db: Session, user: User) -> dict[str, Any]:
    projects = _projects(db, user)
    return {"change_sets": _change_sets(db, user, projects), "packages": _packages(db, user, projects),
            "tickets": _tickets(db, user, projects), "messages": _messages(db, user, projects),
            "notifications": _notifications(db, user), "ai_updates": _ai_updates(db, projects),
            "workspaces": workspaces(projects)}

