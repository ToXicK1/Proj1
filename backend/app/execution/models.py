"""Execution jobs (Phase 1, RD-30): work that runs code or tools, done by the executor service in a fresh, locked-down
container per job. The API and worker only queue jobs and read results; they never talk to Docker."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

JOB_STATUS = ("queued", "running", "succeeded", "failed", "timed_out", "rejected", "error")


class ExecutionJob(Base):
    __tablename__ = "execution_jobs"
    __table_args__ = (CheckConstraint(f"status in {JOB_STATUS}", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    # What runs is chosen by the executor from this kind (an allowlisted template), never by the caller.
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # template inputs, validated twice
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    image: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    limits: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # what the container really got
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")  # combined, truncated, secrets never here
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    failure: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    claimed_by: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
