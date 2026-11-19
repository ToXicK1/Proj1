import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SensorExecution(Base):
    """One deterministic check of one artifact version. Append-only; only the sensor runner writes it."""

    __tablename__ = "sensor_executions"
    __table_args__ = (
        CheckConstraint("status in ('PASS','FAIL','WARNING','NOT_APPLICABLE','ERROR')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True
    )
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("artifact_versions.id"), nullable=False, index=True
    )
    sensor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sensor_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SensorEvidence(Base):
    """A result produced outside the artifact (lint, tests, scans), recorded by an authorized person."""

    __tablename__ = "sensor_evidence"
    __table_args__ = (
        CheckConstraint("outcome in ('pass','fail')", name="outcome_valid"),
        CheckConstraint("source in ('human','sandbox')", name="source_valid"),
        CheckConstraint("source = 'sandbox' or recorded_by is not null", name="human_is_named"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="human", server_default="human")
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("artifact_versions.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(8), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RiskAcceptance(Base):
    """A named person accepting one failed sensor on one artifact version, until a date."""

    __tablename__ = "risk_acceptances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True
    )
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifact_versions.id"), nullable=False)
    sensor_key: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
