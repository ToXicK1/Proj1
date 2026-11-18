import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Artifact(Base):
    """A logical deliverable produced by one stage. Its content lives in versions."""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stage_executions.id"), nullable=False, unique=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    # Points at the newest version. No foreign key: versions reference artifacts, and the
    # application keeps this pointer consistent inside the same transaction.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ArtifactVersion(Base):
    """Immutable content. Changing content means a new row; UPDATE and DELETE are blocked by trigger."""

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version_number", name="uq_artifact_versions_artifact_number"),
        CheckConstraint("author_type in ('system','human')", name="author_type_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    artifact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifacts.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author_type: Mapped[str] = mapped_column(String(20), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
