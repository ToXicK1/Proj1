"""Skill versions gain compatible stages and pinned dependencies.

Revision ID: 0007_skill_stages_deps
Revises: 0006_skills_and_pinning
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_skill_stages_deps"
down_revision = "0006_skills_and_pinning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("compatible_stages", "dependencies"):
        op.add_column(
            "skill_versions",
            sa.Column(column, postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        )


def downgrade() -> None:
    op.drop_column("skill_versions", "dependencies")
    op.drop_column("skill_versions", "compatible_stages")
