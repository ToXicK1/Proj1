"""Spend controls: model prices, monthly budgets, provider pauses, route strategy, cache token counts.

Revision ID: 0021
Revises: 0020_orchestration
Create Date: 2026-11-23 09:48:16.401900
"""
from alembic import op
import sqlalchemy as sa


revision = '0021_spend_controls'
down_revision = '0020_orchestration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('model_prices',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('adapter_type', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=False),
    sa.Column('input_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('output_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('cache_read_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('cache_write_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_model_prices_organization_id_organizations')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_prices')),
    sa.UniqueConstraint('organization_id', 'adapter_type', 'model', name='uq_model_price')
    )
    op.create_index(op.f('ix_model_prices_organization_id'), 'model_prices', ['organization_id'], unique=False)
    op.create_table('spend_budgets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('project_id', sa.Uuid(), nullable=True),
    sa.Column('monthly_limit_micro_usd', sa.BigInteger(), nullable=False),
    sa.Column('warn_percent', sa.Integer(), nullable=False),
    sa.Column('on_limit', sa.String(length=16), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("on_limit in ('pause','free_only')", name=op.f('ck_spend_budgets_on_limit_valid')),
    sa.CheckConstraint('monthly_limit_micro_usd > 0', name=op.f('ck_spend_budgets_limit_valid')),
    sa.CheckConstraint('warn_percent between 1 and 100', name=op.f('ck_spend_budgets_warn_valid')),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_spend_budgets_organization_id_organizations')),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_spend_budgets_project_id_projects')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_spend_budgets')),
    sa.UniqueConstraint('organization_id', 'project_id', name='uq_spend_budget', postgresql_nulls_not_distinct=True)
    )
    op.create_index(op.f('ix_spend_budgets_organization_id'), 'spend_budgets', ['organization_id'], unique=False)
    op.add_column('ai_providers', sa.Column('paused_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('ai_providers', sa.Column('paused_reason', sa.String(length=120), nullable=True))
    op.add_column('model_routes', sa.Column('strategy', sa.String(length=16), server_default='ordered', nullable=False))
    op.add_column('token_usage', sa.Column('cache_read_tokens', sa.Integer(), server_default='0', nullable=False))
    op.add_column('token_usage', sa.Column('cache_write_tokens', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('token_usage', 'cache_write_tokens')
    op.drop_column('token_usage', 'cache_read_tokens')
    op.drop_column('model_routes', 'strategy')
    op.drop_column('ai_providers', 'paused_reason')
    op.drop_column('ai_providers', 'paused_until')
    op.drop_index(op.f('ix_spend_budgets_organization_id'), table_name='spend_budgets')
    op.drop_table('spend_budgets')
    op.drop_index(op.f('ix_model_prices_organization_id'), table_name='model_prices')
    op.drop_table('model_prices')
