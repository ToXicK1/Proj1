"""Test fixtures: an embedded PostgreSQL server (pgserver), a fresh database per test, migrations applied.

No Docker and no system PostgreSQL install are needed for the test suite.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pgserver
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import Settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_SECRET = "test-only-signing-key-0123456789abcdef"


@pytest.fixture(scope="session")
def pg_base_url() -> Iterator[str]:
    server = pgserver.get_server(str(BACKEND_DIR / ".pgtest" / "data"), cleanup_mode="stop")
    uri = server.get_uri()  # postgresql://user:@host:port/postgres
    yield uri.replace("postgresql://", "postgresql+pg8000://", 1)


def _admin_engine(base_url: str) -> Engine:
    return create_engine(base_url, isolation_level="AUTOCOMMIT")


def _migrate(url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture
def db_url(pg_base_url: str) -> Iterator[str]:
    name = f"t_{uuid.uuid4().hex}"
    admin = _admin_engine(pg_base_url)
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = pg_base_url.rsplit("/", 1)[0] + f"/{name}"
    _migrate(url)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def settings(db_url: str) -> Settings:
    return Settings(
        app_env="test",
        database_url=db_url,
        secret_key=TEST_SECRET,
        public_base_url="http://testserver",
        cookie_secure=False,
        login_max_failures=5,
        login_lockout_minutes=15,
        auth_rate_limit_per_minute=1000,
        signup_mode="personal",  # most tests work inside one private organization per account
    )


@pytest.fixture
def app(settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(settings)
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app):  # type: ignore[no-untyped-def]
    with TestClient(app) as c:
        yield c


@pytest.fixture
def engine(db_url: str) -> Iterator[Engine]:
    eng = create_engine(db_url)
    yield eng
    eng.dispose()
