"""orchestration tools routing records

Revision ID: 0020_orchestration
Revises: 0019_engine_phase5
Create Date: 2026-11-20 15:01:27.128698
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0020_orchestration'
down_revision = '0019_engine_phase5'
branch_labels = None
depends_on = None


KIND = "ck_agent_configurations_ck_agent_configurations_kind_valid"


def upgrade() -> None:
    # A third agent kind: support specialists that advise a lead
    op.execute(f"ALTER TABLE agent_configurations DROP CONSTRAINT {KIND}")
    op.execute(f"ALTER TABLE agent_configurations ADD CONSTRAINT {KIND} CHECK (kind in ('lead','reviewer','specialist'))")
    op.create_table('routing_policies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('task', sa.String(length=32), nullable=False),
    sa.Column('profile_key', sa.String(length=64), nullable=True),
    sa.Column('route_key', sa.String(length=64), nullable=False),
    sa.Column('require_different_provider', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("task in ('lead','reviewer','specialist','answer','triage')", name=op.f('ck_routing_policies_task_valid')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_routing_policies_organization_id_organizations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_routing_policies')),
    sa.UniqueConstraint('organization_id', 'task', 'profile_key', name='uq_routing_policy')
    )
    op.create_index(op.f('ix_routing_policies_organization_id'), 'routing_policies', ['organization_id'], unique=False)
    op.create_table('tool_executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('agent_run_id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=False),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('permission_class', sa.String(length=32), nullable=False),
    sa.Column('arguments', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('summary', sa.String(length=300), nullable=False),
    sa.Column('result_chars', sa.Integer(), nullable=False),
    sa.Column('result_sha256', sa.String(length=64), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_runs.id'], name=op.f('fk_tool_executions_agent_run_id_agent_runs')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_tool_executions_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_tool_executions_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_executions'))
    )
    op.create_index(op.f('ix_tool_executions_agent_run_id'), 'tool_executions', ['agent_run_id'], unique=False)
    op.create_index(op.f('ix_tool_executions_project_id'), 'tool_executions', ['project_id'], unique=False)
    op.add_column('agent_runs', sa.Column('profile_key', sa.String(length=64), nullable=True))
    op.add_column('agent_runs', sa.Column('task', sa.String(length=32), nullable=True))
    op.add_column('agent_runs', sa.Column('context_digest', sa.String(length=64), nullable=True))
    op.add_column('agent_runs', sa.Column('input_versions', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                                          server_default=sa.text("'[]'::jsonb")))
    op.alter_column('agent_runs', 'input_versions', server_default=None)
    op.add_column('agent_runs', sa.Column('tool_grants', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                                          server_default=sa.text("'[]'::jsonb")))
    op.alter_column('agent_runs', 'tool_grants', server_default=None)
    op.add_column('agent_runs', sa.Column('output_artifact_version_id', sa.Uuid(), nullable=True))
    op.add_column('agent_runs', sa.Column('correlation_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_agent_runs_correlation_id'), 'agent_runs', ['correlation_id'], unique=False)


def downgrade() -> None:
    specialists = op.get_bind().execute(sa.text("select count(*) from agent_configurations where kind = 'specialist'")).scalar()
    if specialists:
        raise RuntimeError(f"{specialists} specialist agent(s) exist; remove them before downgrading")
    op.execute(f"ALTER TABLE agent_configurations DROP CONSTRAINT {KIND}")
    op.execute(f"ALTER TABLE agent_configurations ADD CONSTRAINT {KIND} CHECK (kind in ('lead','reviewer'))")
    op.drop_index(op.f('ix_agent_runs_correlation_id'), table_name='agent_runs')
    op.drop_column('agent_runs', 'correlation_id')
    op.drop_column('agent_runs', 'output_artifact_version_id')
    op.drop_column('agent_runs', 'tool_grants')
    op.drop_column('agent_runs', 'input_versions')
    op.drop_column('agent_runs', 'context_digest')
    op.drop_column('agent_runs', 'task')
    op.drop_column('agent_runs', 'profile_key')
    op.drop_index(op.f('ix_tool_executions_project_id'), table_name='tool_executions')
    op.drop_index(op.f('ix_tool_executions_agent_run_id'), table_name='tool_executions')
    op.drop_table('tool_executions')
    op.drop_index(op.f('ix_routing_policies_organization_id'), table_name='routing_policies')
    op.drop_table('routing_policies')
