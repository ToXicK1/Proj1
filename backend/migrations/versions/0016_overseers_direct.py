"""administrators and project managers, direct messages

Revision ID: 0016_overseers_direct
Revises: 0015_team_chat
Create Date: 2026-11-19 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016_overseers_direct'
down_revision = '0015_team_chat'
branch_labels = None
depends_on = None

ROLE = "ck_memberships_ck_memberships_role_valid"


def upgrade() -> None:
    op.add_column('team_messages', sa.Column('recipient_user_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_team_messages_recipient_user_id'), 'team_messages', ['recipient_user_id'], unique=False)
    op.create_foreign_key(op.f('fk_team_messages_recipient_user_id_users'), 'team_messages', 'users',
                          ['recipient_user_id'], ['id'])
    op.execute(f"ALTER TABLE memberships DROP CONSTRAINT {ROLE}")
    op.execute(f"ALTER TABLE memberships ADD CONSTRAINT {ROLE} "
               "CHECK (role in ('org_admin','project_manager','project_owner','member'))")
    # Existing administrators can now see every project of their organization.
    op.execute("""
        INSERT INTO project_members (id, project_id, user_id, project_role)
        SELECT gen_random_uuid(), p.id, m.user_id, 'viewer'
        FROM memberships m JOIN projects p ON p.organization_id = m.organization_id
        WHERE m.role = 'org_admin' AND m.status = 'active'
          AND NOT EXISTS (SELECT 1 FROM project_members pm WHERE pm.project_id = p.id AND pm.user_id = m.user_id)
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM memberships WHERE role = 'project_manager')
               OR EXISTS (SELECT 1 FROM team_messages WHERE recipient_user_id IS NOT NULL) THEN
                RAISE EXCEPTION 'project managers or direct messages exist; the older schema cannot hold them';
            END IF;
        END $$
    """)
    op.execute(f"ALTER TABLE memberships DROP CONSTRAINT {ROLE}")
    op.execute(f"ALTER TABLE memberships ADD CONSTRAINT {ROLE} CHECK (role in ('org_admin','project_owner','member'))")
    op.drop_constraint(op.f('fk_team_messages_recipient_user_id_users'), 'team_messages', type_='foreignkey')
    op.drop_index(op.f('ix_team_messages_recipient_user_id'), table_name='team_messages')
    op.drop_column('team_messages', 'recipient_user_id')
