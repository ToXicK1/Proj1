"""Platform-assembled drafts: the system_draft provenance and system-authored record versions.

Revision ID: 0025_system_drafts
Revises: 0024_assistant
Create Date: 2026-11-23 16:41:02.671864
"""
from alembic import op
import sqlalchemy as sa


revision = '0025_system_drafts'
down_revision = '0024_assistant'
branch_labels = None
depends_on = None


OLD = "('confirmed', 'assumption', 'ai_suggestion', 'open_question')"
NEW = "('confirmed', 'assumption', 'ai_suggestion', 'open_question', 'system_draft')"


def _provenance(values: str) -> None:
    for table in ("work_items", "work_item_versions"):
        op.drop_constraint(op.f(f"ck_{table}_provenance_valid"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_provenance_valid"), table, f"provenance in {values}")


def upgrade() -> None:
    _provenance(NEW)
    op.drop_constraint(op.f("ck_work_item_versions_author_type_valid"), "work_item_versions", type_="check")
    op.create_check_constraint(op.f("ck_work_item_versions_author_type_valid"), "work_item_versions",
                               "author_type in ('human','ai','system')")


def downgrade() -> None:
    _provenance(OLD)
    op.drop_constraint(op.f("ck_work_item_versions_author_type_valid"), "work_item_versions", type_="check")
    op.create_check_constraint(op.f("ck_work_item_versions_author_type_valid"), "work_item_versions",
                               "author_type in ('human','ai')")
