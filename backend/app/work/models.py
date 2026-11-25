"""Work records: a department's working objects (requirements, stories, diagrams, test cases...), versioned.

A record's content lives in immutable versions. What is approved is a package: a frozen list of exact record
versions (RD-17). AI agents can only propose records and comment; submitting and deciding packages is human-only.
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

# system_draft: assembled by the platform from approved records (a BRD or SRS draft), never by the AI.
PROVENANCE = ("confirmed", "assumption", "ai_suggestion", "open_question", "system_draft")
ITEM_STATUS = ("draft", "in_review", "approved", "changes_requested", "archived")


class WorkItem(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_work_item_key"),
        CheckConstraint(f"provenance in {PROVENANCE}", name="provenance_valid"),
        CheckConstraint(f"status in {ITEM_STATUS}", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    key: Mapped[str] = mapped_column(String(24), nullable=False)  # REQ-012: shown to people, unique per project
    title: Mapped[str] = mapped_column(String(300), nullable=False)  # of the current version, for search and lists
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    provenance: Mapped[str] = mapped_column(String(24), nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    # The lifecycle step whose AI output proposed this record, if any.
    stage_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stage_executions.id"),
                                                                 nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkItemVersion(Base):
    """Immutable (append-only trigger). Every edit is a new row with its author and reason."""

    __tablename__ = "work_item_versions"
    __table_args__ = (
        UniqueConstraint("item_id", "number", name="uq_work_item_version"),
        CheckConstraint("author_type in ('human','ai','system')", name="author_type_valid"),
        CheckConstraint(f"provenance in {PROVENANCE}", name="provenance_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provenance: Mapped[str] = mapped_column(String(24), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author_type: Mapped[str] = mapped_column(String(8), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    author_agent: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Where an AI proposal came from: artifact versions, record versions or brief fields it used.
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


LINK_TYPES = ("derives_from", "implements", "tests", "depends_on", "blocks", "designs", "relates_to")


class WorkItemLink(Base):
    __tablename__ = "work_item_links"
    __table_args__ = (
        UniqueConstraint("from_item_id", "to_item_id", "link_type", name="uq_work_item_link"),
        CheckConstraint(f"link_type in {LINK_TYPES}", name="link_type_valid"),
        CheckConstraint("from_item_id <> to_item_id", name="not_self"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    from_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=False)
    to_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=False)
    link_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkComment(Base):
    """A comment on one exact record version, optionally anchored to a field or a pinned position."""

    __tablename__ = "work_comments"
    __table_args__ = (CheckConstraint("author_type in ('human','ai')", name="author_type_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=False, index=True)
    item_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_item_versions.id"), nullable=False)
    anchor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {"field": "..."} or {"x": .., "y": ..}
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_type: Mapped[str] = mapped_column(String(8), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


PACKAGE_STATUS = ("submitted", "approved", "changes_requested", "superseded")


class WorkPackage(Base):
    """A department's deliverable for review: the exact record versions it contains, frozen at submission."""

    __tablename__ = "work_packages"
    __table_args__ = (CheckConstraint(f"status in {PACKAGE_STATUS}", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, ... per project and department
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="submitted")
    snapshot: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{item_id, key, version_id, number, sha256,
    #                                                                   content_author}]
    # Set when the package is the deliverable of a lifecycle step: the artifact version the gate approves.
    stage_execution_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("stage_executions.id"),
                                                                 nullable=True)
    artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("artifact_versions.id"),
                                                                  nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    submitted_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    # The client's decision on an approved project brief (after the PM): None (not asked), awaiting, approved or
    # changes_requested. Only a client-approved brief starts delivery.
    client_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    client_decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    client_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    client_note: Mapped[str] = mapped_column(String(2000), nullable=False, default="", server_default="")


class WorkAttachment(Base):
    """A file attached to a record (a meeting's documents, references). The bytes live in object storage; this row
    says which record they belong to and who added them. Never served to anyone who cannot read the record."""

    __tablename__ = "work_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_items.id"), nullable=False, index=True)
    stored_object_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stored_objects.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


HANDOFF_STATUS = ("sent", "acknowledged", "clarification_requested")


class Handoff(Base):
    """A department passing an approved package to another. Records who, what (exact versions), when, and the reply.
    A handoff never changes workflow state and is never an approval."""

    __tablename__ = "handoffs"
    __table_args__ = (CheckConstraint(f"status in {HANDOFF_STATUS}", name="status_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("work_packages.id"), nullable=False)
    from_department: Mapped[str] = mapped_column(String(64), nullable=False)
    to_department: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="sent")
    sender_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    reply: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    replied_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
