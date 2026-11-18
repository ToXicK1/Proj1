import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

DECISIONS = ("APPROVE", "REJECT", "REQUEST_CHANGES")


class ApprovalDecision(Base):
    """A human decision bound to one artifact version. Append-only: UPDATE and DELETE are blocked.

    Approvals of an older version stop counting once a newer version exists, because the engine
    only counts decisions for the version the stage is currently judging.
    """

    __tablename__ = "approval_decisions"
    __table_args__ = (
        UniqueConstraint("approver_user_id", "idempotency_key", name="uq_approval_decisions_idempotency"),
        CheckConstraint("approver_type in ('human')", name="approver_is_human"),
        CheckConstraint(f"decision in ({', '.join(repr(d) for d in DECISIONS)})", name="decision_valid"),
        Index(
            "uq_approval_one_approve_per_version_approver",
            "artifact_version_id",
            "approver_user_id",
            "approval_epoch",
            unique=True,
            postgresql_where=text("decision = 'APPROVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stage_executions.id"), nullable=False)
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifact_versions.id"), nullable=False)
    approver_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    approver_type: Mapped[str] = mapped_column(String(20), nullable=False, default="human")
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    approval_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChangeRequest(Base):
    """Feedback that asked for changes to one artifact version, linked to the revision that answers it."""

    __tablename__ = "change_requests"
    __table_args__ = (CheckConstraint("status in ('open','resolved')", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True)
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifact_versions.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resulting_artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("artifact_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
