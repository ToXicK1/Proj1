"""The department AI assistant: each question, its answer and its proposals.

Revision ID: 0024_assistant
Revises: 0023_stage_records
Create Date: 2026-11-23 12:46:05.508568
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0024_assistant'
down_revision = '0023_stage_records'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('assistant_exchanges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('department', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('proposals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('failure', sa.String(length=300), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], name=op.f('fk_assistant_exchanges_item_id_work_items')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_assistant_exchanges_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_assistant_exchanges_project_id_projects')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_assistant_exchanges_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assistant_exchanges'))
    )
    op.create_index(op.f('ix_assistant_exchanges_project_id'), 'assistant_exchanges', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_assistant_exchanges_project_id'), table_name='assistant_exchanges')
    op.drop_table('assistant_exchanges')
