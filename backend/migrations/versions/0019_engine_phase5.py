"""engine dag escalations questions

Revision ID: 0019_engine_phase5
Revises: 0018_ai_activity
Create Date: 2026-11-20 12:21:51.981278
"""
from alembic import op
import sqlalchemy as sa


revision = '0019_engine_phase5'
down_revision = '0018_ai_activity'
branch_labels = None
depends_on = None


STATUS = "ck_stage_executions_ck_stage_executions_status_valid"
OLD = ("NOT_STARTED", "READY", "RUNNING", "AI_COMPLETED", "VALIDATING", "AWAITING_HUMAN_REVIEW", "CHANGES_REQUESTED",
       "REJECTED", "APPROVED", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED", "SKIPPED")
NEW = (*OLD[:6], "AWAITING_USER_INPUT", *OLD[6:])


def _values(states: tuple[str, ...]) -> str:
    return ", ".join(f"'{state}'" for state in states)


def upgrade() -> None:
    op.create_table('stage_dependencies',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('workflow_execution_id', sa.Uuid(), nullable=False),
    sa.Column('stage_key', sa.String(length=64), nullable=False),
    sa.Column('depends_on', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], name=op.f('fk_stage_dependencies_workflow_execution_id_workflow_executions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stage_dependencies')),
    sa.UniqueConstraint('workflow_execution_id', 'stage_key', 'depends_on', name='uq_stage_dependency')
    )
    op.create_index(op.f('ix_stage_dependencies_workflow_execution_id'), 'stage_dependencies', ['workflow_execution_id'], unique=False)
    op.create_table('owner_questions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('stage_execution_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('asked_by', sa.Uuid(), nullable=False),
    sa.Column('question', sa.String(length=2000), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('answer', sa.String(length=4000), nullable=True),
    sa.Column('answered_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('answered_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('open','answered','withdrawn')", name=op.f('ck_owner_questions_status_valid')),
    sa.ForeignKeyConstraint(['answered_by'], ['users.id'], name=op.f('fk_owner_questions_answered_by_users')),
    sa.ForeignKeyConstraint(['asked_by'], ['users.id'], name=op.f('fk_owner_questions_asked_by_users')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_owner_questions_project_id_projects')),
    sa.ForeignKeyConstraint(['stage_execution_id'], ['stage_executions.id'], name=op.f('fk_owner_questions_stage_execution_id_stage_executions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_owner_questions'))
    )
    op.create_index(op.f('ix_owner_questions_project_id'), 'owner_questions', ['project_id'], unique=False)
    op.create_index(op.f('ix_owner_questions_stage_execution_id'), 'owner_questions', ['stage_execution_id'], unique=False)
    op.create_table('stage_escalations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('stage_execution_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('raised_by', sa.Uuid(), nullable=False),
    sa.Column('reason', sa.String(length=2000), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('resolution', sa.String(length=2000), nullable=True),
    sa.Column('resolved_by', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status in ('open','resolved')", name=op.f('ck_stage_escalations_status_valid')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_stage_escalations_project_id_projects')),
    sa.ForeignKeyConstraint(['raised_by'], ['users.id'], name=op.f('fk_stage_escalations_raised_by_users')),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name=op.f('fk_stage_escalations_resolved_by_users')),
    sa.ForeignKeyConstraint(['stage_execution_id'], ['stage_executions.id'], name=op.f('fk_stage_escalations_stage_execution_id_stage_executions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stage_escalations'))
    )
    op.create_index(op.f('ix_stage_escalations_project_id'), 'stage_escalations', ['project_id'], unique=False)
    op.create_index(op.f('ix_stage_escalations_stage_execution_id'), 'stage_escalations', ['stage_execution_id'], unique=False)
    op.add_column('stage_executions', sa.Column('run_job_id', sa.Uuid(), nullable=True))
    # A new state: the professional asked the owner a question about the work.
    op.execute(f"ALTER TABLE stage_executions DROP CONSTRAINT {STATUS}")
    op.execute(f"ALTER TABLE stage_executions ADD CONSTRAINT {STATUS} CHECK (status in ({_values(NEW)}))")
    # The dependency graph of executions already running, as rows.
    op.execute("""
        INSERT INTO stage_dependencies (workflow_execution_id, stage_key, depends_on)
        SELECT e.id, st->>'id', dep
        FROM workflow_executions e
        JOIN workflow_versions v ON v.id = e.workflow_version_id
        CROSS JOIN LATERAL jsonb_array_elements(v.spec_json->'stages') st
        CROSS JOIN LATERAL jsonb_array_elements_text(st->'depends_on') dep
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    waiting = op.get_bind().execute(sa.text("select count(*) from stage_executions where status = 'AWAITING_USER_INPUT'")).scalar()
    if waiting:
        raise RuntimeError(f"{waiting} stage(s) are waiting for the owner's answer; resolve them before downgrading")
    op.execute(f"ALTER TABLE stage_executions DROP CONSTRAINT {STATUS}")
    op.execute(f"ALTER TABLE stage_executions ADD CONSTRAINT {STATUS} CHECK (status in ({_values(OLD)}))")
    op.drop_column('stage_executions', 'run_job_id')
    op.drop_index(op.f('ix_stage_escalations_stage_execution_id'), table_name='stage_escalations')
    op.drop_index(op.f('ix_stage_escalations_project_id'), table_name='stage_escalations')
    op.drop_table('stage_escalations')
    op.drop_index(op.f('ix_owner_questions_stage_execution_id'), table_name='owner_questions')
    op.drop_index(op.f('ix_owner_questions_project_id'), table_name='owner_questions')
    op.drop_table('owner_questions')
    op.drop_index(op.f('ix_stage_dependencies_workflow_execution_id'), table_name='stage_dependencies')
    op.drop_table('stage_dependencies')
