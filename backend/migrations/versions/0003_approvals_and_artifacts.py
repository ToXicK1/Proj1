"""Approvals and artifacts: versioned deliverables, human decisions, change requests, rework count.

Revision ID: 0003_approvals_and_artifacts
Revises: 0002_workflow_engine
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_approvals_and_artifacts"
down_revision = "0002_workflow_engine"
branch_labels = None
depends_on = None

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION block_append_only_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
"""


def _append_only_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER {table}_no_update_delete
        BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION block_append_only_mutation();
        """
    )


def upgrade() -> None:
    op.execute(APPEND_ONLY_FUNCTION)

    op.create_table(
        "artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False, unique=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_artifacts_project_id", "artifacts", ["project_id"])

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("author_type", sa.String(20), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("artifact_id", "version_number", name="uq_artifact_versions_artifact_number"),
        sa.CheckConstraint("author_type in ('system','human')", name="ck_artifact_versions_author_type_valid"),
    )
    op.create_index("ix_artifact_versions_artifact_id", "artifact_versions", ["artifact_id"])
    _append_only_trigger("artifact_versions")

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=False),
        sa.Column("approver_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approver_type", sa.String(20), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("policy_slot", sa.String(16), nullable=True),
        sa.Column("approval_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("validation_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("approver_type in ('human')", name="ck_approval_decisions_approver_is_human"),
        sa.CheckConstraint(
            "decision in ('APPROVE', 'REJECT', 'REQUEST_CHANGES')", name="ck_approval_decisions_decision_valid"
        ),
        sa.UniqueConstraint("approver_user_id", "idempotency_key", name="uq_approval_decisions_idempotency"),
    )
    op.create_index("ix_approval_decisions_project_id", "approval_decisions", ["project_id"])
    op.create_index("ix_approval_decisions_approver_user_id", "approval_decisions", ["approver_user_id"])
    op.create_index(
        "uq_approval_one_approve_per_version_approver",
        "approval_decisions",
        ["artifact_version_id", "approver_user_id", "approval_epoch"],
        unique=True,
        postgresql_where=sa.text("decision = 'APPROVE'"),
    )
    _append_only_trigger("approval_decisions")

    op.create_table(
        "change_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False),
        sa.Column("artifact_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("resulting_artifact_version_id", sa.Uuid(), sa.ForeignKey("artifact_versions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status in ('open','resolved')", name="ck_change_requests_status_valid"),
    )
    op.create_index("ix_change_requests_stage_execution_id", "change_requests", ["stage_execution_id"])

    op.add_column(
        "stage_executions",
        sa.Column("rework_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "stage_executions",
        sa.Column("approval_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint("ck_workflow_executions_status_valid", "workflow_executions", type_="check")
    op.create_check_constraint(
        "ck_workflow_executions_status_valid",
        "workflow_executions",
        "status in ('RUNNING', 'COMPLETED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_executions_status_valid", "workflow_executions", type_="check")
    op.create_check_constraint(
        "ck_workflow_executions_status_valid", "workflow_executions", "status in ('RUNNING')"
    )
    op.drop_column("stage_executions", "approval_epoch")
    op.drop_column("stage_executions", "rework_count")
    op.drop_table("change_requests")
    op.execute("DROP TRIGGER IF EXISTS approval_decisions_no_update_delete ON approval_decisions")
    op.drop_table("approval_decisions")
    op.execute("DROP TRIGGER IF EXISTS artifact_versions_no_update_delete ON artifact_versions")
    op.drop_table("artifact_versions")
    op.drop_table("artifacts")
    op.execute("DROP FUNCTION IF EXISTS block_append_only_mutation()")
