"""The Project Manager: one accountable PM per project, assigned by an administrator (RD-20).

Revision ID: 0027_project_manager
Revises: 0026_managed_accounts
Create Date: 2026-11-24 14:50:50.991122
"""
from alembic import op
import sqlalchemy as sa


revision = '0027_project_manager'
down_revision = '0026_managed_accounts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('project_manager_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_projects_project_manager_id_users'), 'projects', 'users', ['project_manager_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(op.f('fk_projects_project_manager_id_users'), 'projects', type_='foreignkey')
    op.drop_column('projects', 'project_manager_id')
