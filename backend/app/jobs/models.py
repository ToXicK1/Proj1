"""The durable job queue (RD-4). PostgreSQL holds every job; workers claim them with FOR UPDATE SKIP LOCKED."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JOB_STATUSES = ("queued", "running", "done", "failed")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status in ('queued','running','done','failed')", name="status_valid"),
        CheckConstraint("attempts >= 0 and max_attempts >= 1", name="attempts_valid"),
        Index("ix_jobs_claim", "status", "run_after"),
        # One waiting job per subject: a second request for the same work joins the first.
        Index("uq_jobs_waiting_dedupe", "dedupe_key", unique=True,
              postgresql_where=text("status = 'queued' and dedupe_key is not null")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
