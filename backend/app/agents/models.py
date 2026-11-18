import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class Profile(Base):
    """A professional area of responsibility (for example Business Analyst). Agents belong to one."""

    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_profiles_org_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentConfiguration(Base):
    """A named agent. Its behaviour lives in immutable versions. lineage_root_id ties clones together:
    a reviewer that shares a lineage root with its lead is not independent and is refused."""

    __tablename__ = "agent_configurations"
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="uq_agent_configurations_org_key"),
        CheckConstraint("kind in ('lead','reviewer')", name="kind_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    profile_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("profiles.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    lineage_root_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentConfigVersion(Base):
    """Immutable behaviour: instructions, output keys, model route, context sources and tool grants.
    UPDATE and DELETE are blocked by a trigger, so a run can always be traced to the exact version."""

    __tablename__ = "agent_config_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_config_versions_agent_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_configurations.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    required_keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    model_route: Mapped[str] = mapped_column(String(64), nullable=False)
    context_sources: Mapped[list] = mapped_column(JSONB, nullable=False)
    tools: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # Pinned skill versions: [{"key": ..., "version": n}]. Instructions are resolved from these, never from latest.
    skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # False pins the run to the route's primary provider: no fallback candidates.
    allow_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ReviewRecord(Base):
    """A reviewer's verdict on one artifact version, plus the structured handoff it answered."""

    __tablename__ = "review_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True)
    artifact_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("artifact_versions.id"), nullable=False)
    reviewer_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_config_versions.id"), nullable=False)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    findings: Mapped[list] = mapped_column(JSONB, nullable=False)
    handoff: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
