"""Files attached to work records (client meetings and intake, P2).

Revision ID: 0028_meetings_intake
Revises: 0027_project_manager
Create Date: 2026-11-24 15:02:54.613377
"""
from alembic import op
import sqlalchemy as sa


revision = '0028_meetings_intake'
down_revision = '0027_project_manager'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('work_attachments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('stored_object_id', sa.Uuid(), nullable=False),
    sa.Column('filename', sa.String(length=200), nullable=False),
    sa.Column('content_type', sa.String(length=120), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], name=op.f('fk_work_attachments_item_id_work_items')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_attachments_project_id_projects')),
    sa.ForeignKeyConstraint(['stored_object_id'], ['stored_objects.id'], name=op.f('fk_work_attachments_stored_object_id_stored_objects')),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_work_attachments_uploaded_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_attachments'))
    )
    op.create_index(op.f('ix_work_attachments_item_id'), 'work_attachments', ['item_id'], unique=False)
    op.create_index(op.f('ix_work_attachments_project_id'), 'work_attachments', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_work_attachments_project_id'), table_name='work_attachments')
    op.drop_index(op.f('ix_work_attachments_item_id'), table_name='work_attachments')
    op.drop_table('work_attachments')
