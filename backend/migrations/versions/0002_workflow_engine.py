"""Workflow engine: definitions, immutable versions, executions, stage state and transition log.

Revision ID: 0002_workflow_engine
Revises: 0001_foundation
Create Date: 2026-11-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_workflow_engine"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

STAGE_STATUSES = (
    "NOT_STARTED", "READY", "RUNNING", "AI_COMPLETED", "VALIDATING", "AWAITING_HUMAN_REVIEW",
    "CHANGES_REQUESTED", "REJECTED", "APPROVED", "BLOCKED", "FAILED", "CANCELLED", "SKIPPED",
)


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("definition_id", sa.Uuid(), sa.ForeignKey("workflow_definitions.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec_json", postgresql.JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("definition_id", "version", name="uq_workflow_versions_definition_version"),
    )
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status in ('RUNNING')", name="ck_workflow_executions_status_valid"),
    )
    op.create_index("ix_workflow_executions_project_id", "workflow_executions", ["project_id"])
    op.create_table(
        "stage_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_execution_id", sa.Uuid(), sa.ForeignKey("workflow_executions.id"), nullable=False),
        sa.Column("stage_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.String(300), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workflow_execution_id", "stage_key", name="uq_stage_execution_key"),
        sa.CheckConstraint(
            "status in (" + ", ".join(f"'{s}'" for s in STAGE_STATUSES) + ")",
            name="ck_stage_executions_status_valid",
        ),
    )
    op.create_index("ix_stage_executions_workflow_execution_id", "stage_executions", ["workflow_execution_id"])
    op.create_table(
        "stage_transitions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stage_execution_id", sa.Uuid(), sa.ForeignKey("stage_executions.id"), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_stage_transitions_stage_execution_id", "stage_transitions", ["stage_execution_id"])


def downgrade() -> None:
    op.drop_table("stage_transitions")
    op.drop_table("stage_executions")
    op.drop_table("workflow_executions")
    op.drop_table("workflow_versions")
    op.drop_table("workflow_definitions")
