"""AI runs at project level: a run outside the lifecycle has no step (the PM persona, P3).

Revision ID: 0029_project_runs
Revises: 0028_meetings_intake
Create Date: 2026-11-24 16:24:27.105910
"""
from alembic import op
import sqlalchemy as sa


revision = '0029_project_runs'
down_revision = '0028_meetings_intake'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('agent_runs', 'stage_execution_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('agent_runs', 'stage_execution_id',
               existing_type=sa.UUID(),
               nullable=False)
