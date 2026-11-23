import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
    # Skipped by routing until this time: out of credit (until next month), key refused, or briefly after
    # rate limits and outages. An administrator can clear it.
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


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
    # ordered: the primary, then the fallbacks in order. cheapest: the cheapest priced healthy provider first.
    strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="ordered", server_default="ordered")


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
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="lead")
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agent_config_versions.id"), nullable=True)
    # Which sources the run was given (ids and counts, never the content itself).
    context_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # Execution record (AI_ORCHESTRATION.md): what this run was, what it read, what it was allowed, what it made.
    profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # department
    task: Mapped[str | None] = mapped_column(String(32), nullable=True)  # lead, reviewer, specialist, answer, triage
    context_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 of the exact prompt
    input_versions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # artifact versions given
    tool_grants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    output_artifact_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL when no price is configured for the model. Cost is never invented.
    cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ToolExecution(Base):
    """One tool call an agent made: which tool, with what, whether it was allowed, and what came back (by size and
    digest; the content stays where it came from)."""

    __tablename__ = "tool_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False, index=True)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    permission_class: Mapped[str] = mapped_column(String(32), nullable=False)
    arguments: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # ok, refused, error
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    result_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RoutingPolicy(Base):
    """Which model route a kind of AI task uses, optionally per department. The most specific rule wins."""

    __tablename__ = "routing_policies"
    __table_args__ = (UniqueConstraint("organization_id", "task", "profile_key", name="uq_routing_policy"),
                      CheckConstraint("task in ('lead','reviewer','specialist','answer','triage')", name="task_valid"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False,
                                                       index=True)
    task: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    route_key: Mapped[str] = mapped_column(String(64), nullable=False)
    # Reviewer rules only: the review must come from a different provider than the work it reviews.
    require_different_provider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelPrice(Base):
    """An organization's price for one model, overriding the published default. Micro-dollars per million tokens."""

    __tablename__ = "model_prices"
    __table_args__ = (UniqueConstraint("organization_id", "adapter_type", "model", name="uq_model_price"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False,
                                                       index=True)
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_read_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cache_write_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SpendBudget(Base):
    """A monthly spending limit for the organization (project_id empty) or one project."""

    __tablename__ = "spend_budgets"
    __table_args__ = (UniqueConstraint("organization_id", "project_id", name="uq_spend_budget",
                                       postgresql_nulls_not_distinct=True),  # one organization-wide budget
                      CheckConstraint("on_limit in ('pause','free_only')", name="on_limit_valid"),
                      CheckConstraint("warn_percent between 1 and 100", name="warn_valid"),
                      CheckConstraint("monthly_limit_micro_usd > 0", name="limit_valid"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), nullable=False,
                                                       index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=True)
    monthly_limit_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    warn_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    # pause: stop AI work until the limit is raised or the month ends. free_only: keep going on unpriced-free
    # providers only (for example a local model), never on a paid one.
    on_limit: Mapped[str] = mapped_column(String(16), nullable=False, default="pause")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
