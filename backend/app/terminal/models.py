"""Terminal sessions (Phase 2d): a person's shell in its own locked-down container, recorded.

The API creates the session (who, which project, which branch) with a one-time nonce; the executor accepts a
connection only with that nonce, starts the container, and records every input line and the output. The browser never
sees the nonce, and the executor never accepts a connection from anywhere else.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUS = ("requested", "running", "ended", "failed")


class TerminalSession(Base):
    __tablename__ = "terminal_sessions"
    __table_args__ = (CheckConstraint(f"status in {STATUS}", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    nonce: Mapped[str] = mapped_column(String(64), nullable=False, default="")  # one-time; cleared on connect
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    inputs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{at, line}] what the person typed
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="")  # the output, last 200 KB
    input_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
