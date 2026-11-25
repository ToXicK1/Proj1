"""Live workspace events (Phase 1d).

What happens in a project's workspaces (an execution queued, started or finished; a commit; a change set opened,
decided or merged) is appended to `workspace_events` by the code that did it. The browser follows a project's
events over a WebSocket (or the REST endpoint, to catch up), so workspaces update without polling each screen.

Events are a notification channel, not the record: the authoritative state stays in the tables that own it, and an
event carries only identifiers and a short summary, never secrets or file contents. Only the project's internal team
(professionals, managers, administrators) may follow them; the client has its own portal.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import Base

PAGE = 200


class WorkspaceEvent(Base):
    __tablename__ = "workspace_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. execution.finished, change_set.merged
    subject: Mapped[str] = mapped_column(String(100), nullable=False, default="")  # the thing's id
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="")  # user:<id>, agent:<key>, executor
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # ids and a summary only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def publish(db: Session, *, organization_id: uuid.UUID, project_id: uuid.UUID, kind: str, subject: str = "",
            actor: str = "", data: dict[str, Any] | None = None) -> None:
    """Appends one event with the caller's transaction (it is published only if the change commits)."""
    db.add(WorkspaceEvent(organization_id=organization_id, project_id=project_id, kind=kind[:64],
                          subject=subject[:100], actor=actor[:100], data=data or {}))


def event_out(e: WorkspaceEvent) -> dict[str, Any]:
    return {"id": e.id, "kind": e.kind, "subject": e.subject, "actor": e.actor, "data": e.data,
            "at": e.created_at.isoformat() if e.created_at else None}


def after(db: Session, project_id: uuid.UUID, last_id: int, limit: int = PAGE) -> list[WorkspaceEvent]:
    return list(db.execute(select(WorkspaceEvent).where(WorkspaceEvent.project_id == project_id,
                                                        WorkspaceEvent.id > last_id)
                           .order_by(WorkspaceEvent.id).limit(limit)).scalars())


def latest_id(db: Session, project_id: uuid.UUID) -> int:
    return db.execute(select(func.max(WorkspaceEvent.id)).where(WorkspaceEvent.project_id == project_id)
                      ).scalar_one() or 0


def allowed(db: Session, user: Any, project_id: uuid.UUID) -> Any:
    """The project's internal team only."""
    from app.collab.service import scope_for
    from app.core.errors import AppError

    project, scope = scope_for(db, user, project_id)
    if not scope.internal:
        raise AppError(403, "not_permitted", "Workspace events are for the project team")
    return project
