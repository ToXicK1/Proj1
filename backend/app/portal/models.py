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


class IntakeRevision(Base):
    """What the owner told us, item by item, with how each item is known. Confirmed revisions never change."""

    __tablename__ = "intake_revisions"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_intake_project_revision"),
        CheckConstraint("status in ('draft','confirmed')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    items: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # field -> {value, tag, confirmed}
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PortalMessage(Base):
    """The owner's conversation. Kept apart from every internal agent record."""

    __tablename__ = "portal_messages"
    __table_args__ = (CheckConstraint("author_type in ('owner','representative','professional')", name="author_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    author_type: Mapped[str] = mapped_column(String(16), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("artifact_versions.id"),
                                                                  nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OwnerFeedback(Base):
    """Feedback that needs handling. It never changes a deliverable's approval state by itself."""

    __tablename__ = "owner_feedback"
    __table_args__ = (
        CheckConstraint("kind in ('defect','new_requirement','enhancement','usability','security_concern',"
                        "'scope_change')", name="kind_valid"),
        CheckConstraint("status in ('open','triaged','in_progress','resolved','rejected')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("portal_messages.id"), nullable=False)
    artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("artifact_versions.id"),
                                                                  nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    classifier_version: Mapped[str] = mapped_column(String(32), nullable=False)
    classification_reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
