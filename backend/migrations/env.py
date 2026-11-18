import os

from alembic import context

from app.core.db import make_engine
from app.models import metadata

config = context.config


def _url() -> str:
    # Tests and tooling set sqlalchemy.url; otherwise use the application setting.
    return config.get_main_option("sqlalchemy.url") or os.environ.get(
        "AIDLC_DATABASE_URL", "postgresql+pg8000://aidlc:aidlc@localhost:5432/aidlc"
    )


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
