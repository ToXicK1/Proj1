"""Work records and packages linked to lifecycle steps.

Revision ID: 0023_stage_records
Revises: 0022_work_records
Create Date: 2026-11-23 11:37:13.522784
"""
from alembic import op
import sqlalchemy as sa


revision = '0023_stage_records'
down_revision = '0022_work_records'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('work_items', sa.Column('stage_execution_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_work_items_stage_execution_id'), 'work_items', ['stage_execution_id'], unique=False)
    op.create_foreign_key(op.f('fk_work_items_stage_execution_id_stage_executions'), 'work_items', 'stage_executions', ['stage_execution_id'], ['id'])
    op.add_column('work_packages', sa.Column('stage_execution_id', sa.Uuid(), nullable=True))
    op.add_column('work_packages', sa.Column('artifact_version_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_work_packages_artifact_version_id_artifact_versions'), 'work_packages', 'artifact_versions', ['artifact_version_id'], ['id'])
    op.create_foreign_key(op.f('fk_work_packages_stage_execution_id_stage_executions'), 'work_packages', 'stage_executions', ['stage_execution_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(op.f('fk_work_packages_stage_execution_id_stage_executions'), 'work_packages', type_='foreignkey')
    op.drop_constraint(op.f('fk_work_packages_artifact_version_id_artifact_versions'), 'work_packages', type_='foreignkey')
    op.drop_column('work_packages', 'artifact_version_id')
    op.drop_column('work_packages', 'stage_execution_id')
    op.drop_constraint(op.f('fk_work_items_stage_execution_id_stage_executions'), 'work_items', type_='foreignkey')
    op.drop_index(op.f('ix_work_items_stage_execution_id'), table_name='work_items')
    op.drop_column('work_items', 'stage_execution_id')
