"""The kind of work on the project, and the client's decision on the project brief (start flow).

Revision ID: 0030_kickoff_client_brief
Revises: 0029_project_runs
Create Date: 2026-11-25 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0030_kickoff_client_brief'
down_revision = '0029_project_runs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('delivery_scope', sa.String(length=32), nullable=True))
    op.add_column('work_packages', sa.Column('client_status', sa.String(length=24), nullable=True))
    op.add_column('work_packages', sa.Column('client_decided_by_user_id', sa.Uuid(), nullable=True))
    op.add_column('work_packages', sa.Column('client_decided_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('work_packages', sa.Column('client_note', sa.String(length=2000), server_default='',
                                             nullable=False))
    op.create_foreign_key('fk_work_packages_client_decided_by_user_id_users', 'work_packages', 'users',
                          ['client_decided_by_user_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_work_packages_client_decided_by_user_id_users', 'work_packages', type_='foreignkey')
    op.drop_column('work_packages', 'client_note')
    op.drop_column('work_packages', 'client_decided_at')
    op.drop_column('work_packages', 'client_decided_by_user_id')
    op.drop_column('work_packages', 'client_status')
    op.drop_column('projects', 'delivery_scope')
