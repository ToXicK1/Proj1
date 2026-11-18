import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

ADAPTERS = ("anthropic", "openai", "gemini", "openai_compatible", "mock")


class SecretReference(Base):
    """Encrypted credential. Holds ciphertext only; the plaintext is never stored or returned."""

    __tablename__ = "secret_references"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiProvider(Base):
    __tablename__ = "ai_providers"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_ai_providers_org_name"),
        CheckConstraint("adapter_type in ('anthropic','openai','gemini','openai_compatible','mock')",
                        name="adapter_valid"),
        CheckConstraint("status in ('active','disabled')", name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    secret_reference_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("secret_references.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_health_ok: Mapped[bool | None] = mapped_column(nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_health_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelRoute(Base):
    """Named route used by stages: a primary provider and model, then fallbacks in order."""

    __tablename__ = "model_routes"
    __table_args__ = (UniqueConstraint("organization_id", "key", name="uq_model_routes_org_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_provider_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_providers.id"), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(120), nullable=False)
    fallbacks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentRun(Base):
    """One provider call attempt for a stage. Holds metadata only: no prompts, no outputs, no keys."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    stage_execution_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stage_executions.id"), nullable=False, index=True)
    route_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_providers.id"), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL when no price is configured for the model. Cost is never invented.
    cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
