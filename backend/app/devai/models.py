"""Developer AI runs (Phase 2e): one task given to the Developer AI, from request to a change set for human review.

A run records who asked, the task and the story it implements (the exact story version), the agent version that did
the work, its own work branch, every step it took (plan, commits, build and test results, repairs) and the change set
it opened. The AI never approves or merges: the change set goes to an engineer who is neither the AI nor the person who
asked for the work.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

STATUS = ("queued", "working", "in_review", "checks_failed", "failed", "cancelled")
ACTIVE = ("queued", "working")


class DeveloperAiRun(Base):
    __tablename__ = "developer_ai_runs"
    __table_args__ = (CheckConstraint(f"status in {STATUS}", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # per project, for the branch name
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False, default="")
    story_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=True)
    story_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("work_item_versions.id"),
                                                               nullable=True)
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    branch: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agent_config_versions.id"),
                                                               nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # [{at, step, text, data}]
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # rounds of code written
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    checks_passed: Mapped[bool | None] = mapped_column(nullable=True)
    change_set_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("change_sets.id"), nullable=True)
    failure: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
