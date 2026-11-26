"""Terminal sessions in the API (Phase 2d): who may open one, the record of each, and the relay to the executor."""

import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import append_event, org_chain
from app.auth.models import User
from app.core.db import uuid7
from app.core.errors import AppError, not_found
from app.terminal.models import TerminalSession


def open_session(db: Session, user: User, project_id: uuid.UUID, branch: str) -> TerminalSession:
    """Engineering professionals and administrators, on a project with a repository. Audited."""
    from app.events.service import publish
    from app.execution.service import _allowed
    from app.repos.service import BRANCH, _repo

    project = _allowed(db, user, project_id)
    _repo(db, project.id)
    if not BRANCH.match(branch):
        raise AppError(422, "invalid_branch", "Choose a branch of the repository")
    row = TerminalSession(id=uuid7(), organization_id=project.organization_id, project_id=project.id,
                          user_id=user.id, branch=branch, status="requested", nonce=secrets.token_urlsafe(32))
    db.add(row)
    append_event(db, chain_key=org_chain(project.organization_id), event_type="terminal.opened", actor_type="human",
                 actor_id=str(user.id), organization_id=project.organization_id, project_id=project.id,
                 payload={"session": str(row.id), "branch": branch})
    publish(db, organization_id=project.organization_id, project_id=project.id, kind="terminal.opened",
            subject=str(row.id), actor=f"user:{user.id}", data={"branch": branch})
    db.commit()
    return row


def session_out(row: TerminalSession, full: bool = False) -> dict[str, Any]:
    out = {"id": str(row.id), "branch": row.branch, "status": row.status, "limits": row.limits,
           "input_count": row.input_count, "end_reason": row.end_reason,
           "created_at": row.created_at.isoformat() if row.created_at else None,
           "started_at": row.started_at.isoformat() if row.started_at else None,
           "ended_at": row.ended_at.isoformat() if row.ended_at else None}
    if full:
        out |= {"inputs": row.inputs, "transcript": row.transcript}
    return out


def get(db: Session, user: User, project_id: uuid.UUID, session_id: uuid.UUID) -> TerminalSession:
    """The record: the person who opened it, or an administrator."""
    from app.collab.service import scope_for

    _, scope = scope_for(db, user, project_id)
    row = db.get(TerminalSession, session_id)
    if row is None or row.project_id != project_id or (row.user_id != user.id and scope.kind != "admin"):
        raise not_found()
    return row


def recent(db: Session, user: User, project_id: uuid.UUID) -> list[TerminalSession]:
    from app.collab.service import scope_for

    _, scope = scope_for(db, user, project_id)
    query = select(TerminalSession).where(TerminalSession.project_id == project_id)
    if scope.kind != "admin":
        query = query.where(TerminalSession.user_id == user.id)
    return list(db.execute(query.order_by(TerminalSession.created_at.desc()).limit(30)).scalars())


def connectable(db: Session, user: User, project_id: uuid.UUID, session_id: uuid.UUID) -> str | None:
    """The nonce to hand to the executor, if this person may connect this session now; else None."""
    from app.execution.service import _allowed

    try:
        _allowed(db, user, project_id)
    except AppError:
        return None
    row = db.get(TerminalSession, session_id)
    if row is None or row.project_id != project_id or row.user_id != user.id or row.status != "requested":
        return None
    return row.nonce
