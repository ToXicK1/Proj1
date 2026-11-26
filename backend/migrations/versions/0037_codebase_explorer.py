"""Codebase Explorer: per-branch analysis state, the repository's files and their dependencies (no source code).

Revision ID: 0037_codebase_explorer
Revises: 0036_developer_ai_runs
Create Date: 2026-11-26 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0037_codebase_explorer'
down_revision = '0036_developer_ai_runs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('code_indexes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('commit', sa.String(length=40), nullable=False),
    sa.Column('requested_commit', sa.String(length=40), nullable=False),
    sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('failure', sa.String(length=300), nullable=False),
    sa.Column('requested_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('indexing', 'up_to_date', 'partial', 'failed')", name=op.f('ck_code_indexes_status_valid')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_code_indexes_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_code_indexes_project_id_projects')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_code_indexes_repository_id_repositories')),
    sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'], name=op.f('fk_code_indexes_requested_by_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_code_indexes')),
    sa.UniqueConstraint('repository_id', 'branch', name='uq_code_indexes_repo_branch')
    )
    op.create_index(op.f('ix_code_indexes_project_id'), 'code_indexes', ['project_id'], unique=False)
    op.create_table('repository_files',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('relative_path', sa.String(length=500), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('extension', sa.String(length=32), nullable=False),
    sa.Column('file_type', sa.String(length=16), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=40), nullable=False),
    sa.Column('analysis_status', sa.String(length=24), nullable=False),
    sa.Column('analysis_error', sa.String(length=200), nullable=False),
    sa.Column('imports', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('last_indexed_commit', sa.String(length=40), nullable=False),
    sa.Column('indexed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_repository_files_project_id_projects')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_repository_files_repository_id_repositories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_repository_files')),
    sa.UniqueConstraint('repository_id', 'branch', 'relative_path', name='uq_repository_files_repo_branch_path')
    )
    op.create_table('file_dependencies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('branch', sa.String(length=100), nullable=False),
    sa.Column('source_file_id', sa.Uuid(), nullable=False),
    sa.Column('target_file_id', sa.Uuid(), nullable=True),
    sa.Column('target_spec', sa.String(length=300), nullable=False),
    sa.Column('relationship_type', sa.String(length=16), nullable=False),
    sa.Column('discovery_method', sa.String(length=24), nullable=False),
    sa.Column('resolution_status', sa.String(length=16), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('line', sa.Integer(), nullable=True),
    sa.Column('last_indexed_commit', sa.String(length=40), nullable=False),
    sa.CheckConstraint("relationship_type in ('imports', 're_exports', 'requires', 'dynamic_import', 'tests')", name=op.f('ck_file_dependencies_relationship_valid')),
    sa.CheckConstraint("resolution_status in ('confirmed', 'partial', 'unresolved', 'external', 'dynamic')", name=op.f('ck_file_dependencies_resolution_valid')),
    sa.CheckConstraint("target_file_id is not null or resolution_status <> 'confirmed'", name=op.f('ck_file_dependencies_confirmed_has_target')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_file_dependencies_repository_id_repositories')),
    sa.ForeignKeyConstraint(['source_file_id'], ['repository_files.id'], name=op.f('fk_file_dependencies_source_file_id_repository_files'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_file_id'], ['repository_files.id'], name=op.f('fk_file_dependencies_target_file_id_repository_files'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_file_dependencies'))
    )
    op.create_index('ix_file_dependencies_repo_branch', 'file_dependencies', ['repository_id', 'branch'], unique=False)
    op.create_index('ix_file_dependencies_source', 'file_dependencies', ['source_file_id'], unique=False)
    op.create_index('ix_file_dependencies_target', 'file_dependencies', ['target_file_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_file_dependencies_target', table_name='file_dependencies')
    op.drop_index('ix_file_dependencies_source', table_name='file_dependencies')
    op.drop_index('ix_file_dependencies_repo_branch', table_name='file_dependencies')
    op.drop_table('file_dependencies')
    op.drop_table('repository_files')
    op.drop_index(op.f('ix_code_indexes_project_id'), table_name='code_indexes')
    op.drop_table('code_indexes')
