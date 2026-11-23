"""Work records: versioned department records, links, comments, packages and handoffs.

Revision ID: 0022_work_records
Revises: 0021_spend_controls
Create Date: 2026-11-23 11:05:27.908737
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0022_work_records'
down_revision = '0021_spend_controls'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('work_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('department', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=48), nullable=False),
    sa.Column('key', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('provenance', sa.String(length=24), nullable=False),
    sa.Column('current_version_id', sa.Uuid(), nullable=True),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('owner_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("provenance in ('confirmed', 'assumption', 'ai_suggestion', 'open_question')", name=op.f('ck_work_items_provenance_valid')),
    sa.CheckConstraint("status in ('draft', 'in_review', 'approved', 'changes_requested', 'archived')", name=op.f('ck_work_items_status_valid')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_work_items_organization_id_organizations')),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_work_items_owner_user_id_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_items_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_items')),
    sa.UniqueConstraint('project_id', 'key', name='uq_work_item_key')
    )
    op.create_index(op.f('ix_work_items_project_id'), 'work_items', ['project_id'], unique=False)
    op.create_table('work_packages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('department', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('note', sa.String(length=2000), nullable=False),
    sa.Column('submitted_by_user_id', sa.Uuid(), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.String(length=2000), nullable=False),
    sa.CheckConstraint("status in ('submitted', 'approved', 'changes_requested', 'superseded')", name=op.f('ck_work_packages_status_valid')),
    sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], name=op.f('fk_work_packages_decided_by_user_id_users')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_work_packages_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_packages_project_id_projects')),
    sa.ForeignKeyConstraint(['submitted_by_user_id'], ['users.id'], name=op.f('fk_work_packages_submitted_by_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_packages'))
    )
    op.create_index(op.f('ix_work_packages_project_id'), 'work_packages', ['project_id'], unique=False)
    op.create_table('handoffs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('package_id', sa.Uuid(), nullable=False),
    sa.Column('from_department', sa.String(length=64), nullable=False),
    sa.Column('to_department', sa.String(length=64), nullable=False),
    sa.Column('note', sa.String(length=2000), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('sender_user_id', sa.Uuid(), nullable=False),
    sa.Column('reply', sa.String(length=2000), nullable=False),
    sa.Column('replied_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status in ('sent', 'acknowledged', 'clarification_requested')", name=op.f('ck_handoffs_status_valid')),
    sa.ForeignKeyConstraint(['package_id'], ['work_packages.id'], name=op.f('fk_handoffs_package_id_work_packages')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_handoffs_project_id_projects')),
    sa.ForeignKeyConstraint(['replied_by_user_id'], ['users.id'], name=op.f('fk_handoffs_replied_by_user_id_users')),
    sa.ForeignKeyConstraint(['sender_user_id'], ['users.id'], name=op.f('fk_handoffs_sender_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_handoffs'))
    )
    op.create_index(op.f('ix_handoffs_project_id'), 'handoffs', ['project_id'], unique=False)
    op.create_table('work_item_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('from_item_id', sa.Uuid(), nullable=False),
    sa.Column('to_item_id', sa.Uuid(), nullable=False),
    sa.Column('link_type', sa.String(length=24), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("link_type in ('derives_from', 'implements', 'tests', 'depends_on', 'blocks', 'designs', 'relates_to')", name=op.f('ck_work_item_links_link_type_valid')),
    sa.CheckConstraint('from_item_id <> to_item_id', name=op.f('ck_work_item_links_not_self')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_work_item_links_created_by_user_id_users')),
    sa.ForeignKeyConstraint(['from_item_id'], ['work_items.id'], name=op.f('fk_work_item_links_from_item_id_work_items')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_item_links_project_id_projects')),
    sa.ForeignKeyConstraint(['to_item_id'], ['work_items.id'], name=op.f('fk_work_item_links_to_item_id_work_items')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_item_links')),
    sa.UniqueConstraint('from_item_id', 'to_item_id', 'link_type', name='uq_work_item_link')
    )
    op.create_index(op.f('ix_work_item_links_project_id'), 'work_item_links', ['project_id'], unique=False)
    op.create_table('work_item_versions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('provenance', sa.String(length=24), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('author_type', sa.String(length=8), nullable=False),
    sa.Column('author_user_id', sa.Uuid(), nullable=True),
    sa.Column('author_agent', sa.String(length=120), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("author_type in ('human','ai')", name=op.f('ck_work_item_versions_author_type_valid')),
    sa.CheckConstraint("provenance in ('confirmed', 'assumption', 'ai_suggestion', 'open_question')", name=op.f('ck_work_item_versions_provenance_valid')),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], name=op.f('fk_work_item_versions_author_user_id_users')),
    sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], name=op.f('fk_work_item_versions_item_id_work_items')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_item_versions')),
    sa.UniqueConstraint('item_id', 'number', name='uq_work_item_version')
    )
    op.create_index(op.f('ix_work_item_versions_item_id'), 'work_item_versions', ['item_id'], unique=False)
    op.create_table('work_comments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('item_version_id', sa.Uuid(), nullable=False),
    sa.Column('anchor', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('author_type', sa.String(length=8), nullable=False),
    sa.Column('author_user_id', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("author_type in ('human','ai')", name=op.f('ck_work_comments_author_type_valid')),
    sa.ForeignKeyConstraint(['author_user_id'], ['users.id'], name=op.f('fk_work_comments_author_user_id_users')),
    sa.ForeignKeyConstraint(['item_id'], ['work_items.id'], name=op.f('fk_work_comments_item_id_work_items')),
    sa.ForeignKeyConstraint(['item_version_id'], ['work_item_versions.id'], name=op.f('fk_work_comments_item_version_id_work_item_versions')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_work_comments_project_id_projects')),
    sa.ForeignKeyConstraint(['resolved_by_user_id'], ['users.id'], name=op.f('fk_work_comments_resolved_by_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_comments'))
    )
    op.create_index(op.f('ix_work_comments_item_id'), 'work_comments', ['item_id'], unique=False)
    op.create_index(op.f('ix_work_comments_project_id'), 'work_comments', ['project_id'], unique=False)
    op.execute("""
        CREATE TRIGGER work_item_versions_no_update_delete
        BEFORE UPDATE OR DELETE ON work_item_versions
        FOR EACH ROW EXECUTE FUNCTION block_append_only_mutation();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS work_item_versions_no_update_delete ON work_item_versions")
    op.drop_index(op.f('ix_work_comments_project_id'), table_name='work_comments')
    op.drop_index(op.f('ix_work_comments_item_id'), table_name='work_comments')
    op.drop_table('work_comments')
    op.drop_index(op.f('ix_work_item_versions_item_id'), table_name='work_item_versions')
    op.drop_table('work_item_versions')
    op.drop_index(op.f('ix_work_item_links_project_id'), table_name='work_item_links')
    op.drop_table('work_item_links')
    op.drop_index(op.f('ix_handoffs_project_id'), table_name='handoffs')
    op.drop_table('handoffs')
    op.drop_index(op.f('ix_work_packages_project_id'), table_name='work_packages')
    op.drop_table('work_packages')
    op.drop_index(op.f('ix_work_items_project_id'), table_name='work_items')
    op.drop_table('work_items')
