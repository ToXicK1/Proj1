"""Skills (versioned instruction sets) and agent version options: pinned skills and fallback control.

Revision ID: 0006_skills_and_pinning
Revises: 0005_agents
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_skills_and_pinning"
down_revision = "0005_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "key", name="uq_skills_org_key"),
    )
    op.create_index("ix_skills_organization_id", "skills", ["organization_id"])

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("skill_id", sa.Uuid(), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("required_tools", postgresql.JSONB(), nullable=False),
        sa.Column("compatible_profiles", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.execute(
        """
        CREATE TRIGGER skill_versions_no_update_delete
        BEFORE UPDATE OR DELETE ON skill_versions
        FOR EACH ROW EXECUTE FUNCTION block_append_only_mutation();
        """
    )

    op.add_column(
        "agent_config_versions",
        sa.Column("skills", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "agent_config_versions",
        sa.Column("allow_fallback", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("agent_config_versions", "allow_fallback")
    op.drop_column("agent_config_versions", "skills")
    op.execute("DROP TRIGGER IF EXISTS skill_versions_no_update_delete ON skill_versions")
    op.drop_table("skill_versions")
    op.drop_table("skills")
