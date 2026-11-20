"""ai activity log

Revision ID: 0018_ai_activity
Revises: 0017_jobs_storage
Create Date: 2026-11-20 10:59:32.847963
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0018_ai_activity'
down_revision = '0017_jobs_storage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_activity',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('job_id', sa.Uuid(), nullable=True),
    sa.Column('stage_key', sa.String(length=64), nullable=True),
    sa.Column('profile_key', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('correlation_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_ai_activity_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_ai_activity_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_activity'))
    )
    op.create_index('ix_ai_activity_project_created', 'ai_activity', ['project_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_ai_activity_project_created', table_name='ai_activity')
    op.drop_table('ai_activity')
