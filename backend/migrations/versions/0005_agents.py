"""Agents: profiles, versioned agent configurations, reviews with handoffs, run provenance.

Revision ID: 0005_agents
Revises: 0004_providers
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_agents"
down_revision = "0004_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_profiles_org_key"),
    )
    op.create_index("ix_profiles_organization_id", "profiles", ["organization_id"])

    op.create_table(
        "agent_configurations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("lineage_root_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_agent_configurations_org_key"),
        sa.CheckConstraint("kind in ('lead','reviewer')", name="ck_agent_configurations_kind_valid"),
    )
    op.create_index("ix_agent_configurations_organization_id", "agent_configurations", ["organization_id"])

    op.create_table(
        "agent_config_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agent_configurations.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("required_keys", postgresql.JSONB(), nullable=False),
        sa.Column("model_route", sa.String(64), nullable=False),
        sa.Column("context_sources", postgresql.JSONB(), nullable=False),
        sa.Column("tools", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_config_versions_agent_version"),
    )
    op.create_index("ix_agent_config_versions_agent_id", "agent_config_versions", ["agent_id"])
    op.execute(
        """
        CREATE TRIGGER agent_config_versions_no_update_delete
        BEFORE UPDATE OR DELETE ON agent_config_versions
        FOR EACH ROW EXECUTE FUNCTION block_append_only_mutation();
        """
    )

    op.create_table(
        "review_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=False),
        sa.Column("reviewer_version_id", sa.Uuid(), sa.ForeignKey("agent_config_versions.id"), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("verdict", sa.String(32), nullable=False),
        sa.Column("findings", postgresql.JSONB(), nullable=False),
        sa.Column("handoff", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_review_records_stage_execution_id", "review_records", ["stage_execution_id"])

    op.add_column("agent_runs", sa.Column("kind", sa.String(16), nullable=False, server_default="lead"))
    op.add_column("agent_runs", sa.Column("agent_version_id", sa.Uuid(), sa.ForeignKey("agent_config_versions.id"), nullable=True))
    op.add_column("agent_runs", sa.Column("context_manifest", postgresql.JSONB(), nullable=False,
                                          server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("agent_runs", "context_manifest")
    op.drop_column("agent_runs", "agent_version_id")
    op.drop_column("agent_runs", "kind")
    op.drop_table("review_records")
    op.execute("DROP TRIGGER IF EXISTS agent_config_versions_no_update_delete ON agent_config_versions")
    op.drop_table("agent_config_versions")
    op.drop_table("agent_configurations")
    op.drop_table("profiles")
