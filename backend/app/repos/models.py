"""Project git repositories and change sets (Phase 1b).

One git repository per project, stored by the executor and changed only through its job containers. Work happens on
branches; a change set is a branch put up for review. A human approves a change set **at an exact commit**: the
approval binds to that SHA, and the default branch changes only by merging the approved commit. Pushing more commits
to the branch after approval makes the approval stale (the same rule as version-bound approvals elsewhere).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CHANGE_SET_STATUS = ("open", "in_review", "approved", "changes_requested", "merged", "closed")


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (CheckConstraint("status in ('creating', 'ready', 'failed')", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, unique=True)
    default_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="creating")
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")  # the default branch's commit
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChangeSet(Base):
    __tablename__ = "change_sets"
    __table_args__ = (CheckConstraint(f"status in {CHANGE_SET_STATUS}", name="status_valid"),
                      UniqueConstraint("project_id", "number", name="uq_change_set_number"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    files: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{path, added, removed}]
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    author_agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=True)
    approved_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    merged_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    merged_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
