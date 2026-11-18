import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
from app.workflows.state_machine import StageStatus

STAGE_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in StageStatus)


class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkflowVersion(Base):
    """Immutable, compiled definition. Executions pin one version for their whole life."""

    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("definition_id", "version", name="uq_workflow_versions_definition_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    definition_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workflow_definitions.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workflow_versions.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (CheckConstraint("status in ('RUNNING', 'COMPLETED')", name="status_valid"),)


class StageExecution(Base):
    __tablename__ = "stage_executions"
    __table_args__ = (
        UniqueConstraint("workflow_execution_id", "stage_key", name="uq_stage_execution_key"),
        CheckConstraint(f"status in ({STAGE_STATUS_VALUES})", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_executions.id"), nullable=False, index=True
    )
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Bumped when an approval is invalidated; only decisions of the current epoch count.
    approval_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StageTransition(Base):
    """Ordered, immutable log of every stage transition. Written in the same transaction as the change."""

    __tablename__ = "stage_transitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
