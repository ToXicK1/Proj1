"""Administrator-created accounts: forced first password change and temporary password expiry.

Revision ID: 0026_managed_accounts
Revises: 0025_system_drafts
Create Date: 2026-11-24 13:25:55.254100
"""
from alembic import op
import sqlalchemy as sa


revision = '0026_managed_accounts'
down_revision = '0025_system_drafts'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('must_change_password', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('temp_password_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'temp_password_expires_at')
    op.drop_column('users', 'must_change_password')
