"""AI providers: encrypted credentials, adapters, model routes, agent runs and token usage.

Revision ID: 0004_providers
Revises: 0003_approvals_and_artifacts
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_providers"
down_revision = "0003_approvals_and_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secret_references",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_secret_references_organization_id", "secret_references", ["organization_id"])

    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("adapter_type", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(300), nullable=True),
        sa.Column("secret_reference_id", sa.Uuid(), sa.ForeignKey("secret_references.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_health_ok", sa.Boolean(), nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_error", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "name", name="uq_ai_providers_org_name"),
        sa.CheckConstraint(
            "adapter_type in ('anthropic','openai','gemini','openai_compatible','mock')",
            name="ck_ai_providers_adapter_valid",
        ),
        sa.CheckConstraint("status in ('active','disabled')", name="ck_ai_providers_status_valid"),
    )
    op.create_index("ix_ai_providers_organization_id", "ai_providers", ["organization_id"])

    op.create_table(
        "model_routes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("primary_provider_id", sa.Uuid(), sa.ForeignKey("ai_providers.id"), nullable=False),
        sa.Column("primary_model", sa.String(120), nullable=False),
        sa.Column("fallbacks", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_model_routes_org_key"),
    )
    op.create_index("ix_model_routes_organization_id", "model_routes", ["organization_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False),
        sa.Column("route_key", sa.String(64), nullable=False),
        sa.Column("provider_id", sa.Uuid(), sa.ForeignKey("ai_providers.id"), nullable=False),
        sa.Column("adapter_type", sa.String(32), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_kind", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_runs_organization_id", "agent_runs", ["organization_id"])
    op.create_index("ix_agent_runs_project_id", "agent_runs", ["project_id"])
    op.create_index("ix_agent_runs_stage_execution_id", "agent_runs", ["stage_execution_id"])

    op.create_table(
        "token_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_token_usage_agent_run_id", "token_usage", ["agent_run_id"])


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_table("agent_runs")
    op.drop_table("model_routes")
    op.drop_table("ai_providers")
    op.drop_table("secret_references")
