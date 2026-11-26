"""Developer AI runs (Phase 2e): a task given to the Developer AI, from request to a change set for human review.

Revision ID: 0036_developer_ai_runs
Revises: 0035_terminal_sessions
Create Date: 2026-11-26 10:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0036_developer_ai_runs'
down_revision = '0035_terminal_sessions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('developer_ai_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('requested_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('task', sa.Text(), nullable=False),
    sa.Column('story_item_id', sa.Uuid(), nullable=True),
    sa.Column('story_version_id', sa.Uuid(), nullable=True),
    sa.Column('base_branch', sa.String(length=100), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('agent_version_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('plan', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('head_sha', sa.String(length=40), nullable=False),
    sa.Column('checks_passed', sa.Boolean(), nullable=True),
    sa.Column('change_set_id', sa.Uuid(), nullable=True),
    sa.Column('failure', sa.String(length=300), nullable=False),
    sa.Column('cancelled_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('queued', 'working', 'in_review', 'checks_failed', 'failed', 'cancelled')", name=op.f('ck_developer_ai_runs_status_valid')),
    sa.ForeignKeyConstraint(['agent_version_id'], ['agent_config_versions.id'], name=op.f('fk_developer_ai_runs_agent_version_id_agent_config_versions')),
    sa.ForeignKeyConstraint(['cancelled_by_user_id'], ['users.id'], name=op.f('fk_developer_ai_runs_cancelled_by_user_id_users')),
    sa.ForeignKeyConstraint(['change_set_id'], ['change_sets.id'], name=op.f('fk_developer_ai_runs_change_set_id_change_sets')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_developer_ai_runs_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_developer_ai_runs_project_id_projects')),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], name=op.f('fk_developer_ai_runs_requested_by_user_id_users')),
    sa.ForeignKeyConstraint(['story_item_id'], ['work_items.id'], name=op.f('fk_developer_ai_runs_story_item_id_work_items')),
    sa.ForeignKeyConstraint(['story_version_id'], ['work_item_versions.id'], name=op.f('fk_developer_ai_runs_story_version_id_work_item_versions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_developer_ai_runs'))
    )
    op.create_index(op.f('ix_developer_ai_runs_project_id'), 'developer_ai_runs', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_developer_ai_runs_project_id'), table_name='developer_ai_runs')
    op.drop_table('developer_ai_runs')
