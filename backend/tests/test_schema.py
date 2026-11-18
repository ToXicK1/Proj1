"""The migration and the SQLAlchemy models must describe the same schema (drift check)."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.models import metadata


def test_migrations_match_models(engine):
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, metadata)
    # The audit trigger and the outbox are not modeled as metadata differences; anything else is drift.
    assert diff == [], diff
