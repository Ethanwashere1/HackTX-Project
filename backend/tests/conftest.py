"""Test setup: a dedicated Postgres database, migrated once per run, truncated after each test.

Uses TEST_DATABASE_URL when set, otherwise database "squadup_test" on the embedded pgserver
Postgres. The schema is dropped and rebuilt with `alembic upgrade head` at the start of the run,
so the run refuses any database whose name lacks "test" or that is the app's DATABASE_URL.
"""

import os

# Before anything reads settings: tests always run as APP_ENV=test (the default is production).
os.environ["APP_ENV"] = "test"

from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlmodel import Session, SQLModel

import app.models  # noqa: F401
from app import db as dbmod
from app.config import BACKEND_DIR, get_settings, is_placeholder


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def db_identity(url: str) -> tuple[str, int, str]:
    """(host, port, database) of a Postgres URL, for comparing URLs written differently."""
    u = make_url(url)
    host = (u.host or str(u.query.get("host") or "localhost")).lower()
    if host in ("127.0.0.1", "::1"):
        host = "localhost"
    return host, u.port or 5432, u.database or ""


def unsafe_test_database_reason(test_url: str, app_url: str | None) -> str | None:
    """Why the destructive test setup must not touch `test_url`, or None if it is safe."""
    host, port, database = db_identity(test_url)
    if "test" not in database.lower():
        return f"test database name {database!r} must contain 'test'"
    if app_url and db_identity(app_url) == (host, port, database):
        return "TEST_DATABASE_URL must not be the same database as DATABASE_URL"
    return None


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    settings = get_settings()
    url = dbmod.get_test_database_url()
    app_url = None if is_placeholder(settings.database_url) else settings.database_url
    reason = unsafe_test_database_reason(url, app_url)
    if reason:
        pytest.exit(f"Refusing to drop the schema: {reason}", 2)
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    command.upgrade(alembic_config(url), "head")
    dbmod.set_engine(url)
    yield url
    dbmod.get_engine().dispose()


@pytest.fixture(autouse=True)
def _isolate(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Known settings for every test, and empty tables afterwards."""
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "dev_login", True)
    monkeypatch.setattr(settings, "frontend_origin", "http://localhost:5173")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "google_client_id", "REPLACE_ME")
    monkeypatch.setattr(settings, "google_client_secret", "REPLACE_ME")
    yield
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    with dbmod.get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    with Session(dbmod.get_engine()) as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def login_as() -> Iterator[Callable[..., TestClient]]:
    """login_as("ana@utexas.edu", "Ana") -> a TestClient with its own signed-in session cookie."""
    from app.main import app

    clients: list[TestClient] = []

    def _login(email: str = "ana@utexas.edu", name: str = "Ana Ruiz") -> TestClient:
        c = TestClient(app)
        resp = c.post("/api/auth/dev-login", json={"email": email, "name": name})
        assert resp.status_code == 200, resp.text
        c.user = resp.json()  # type: ignore[attr-defined]
        clients.append(c)
        return c

    yield _login
    for c in clients:
        c.close()
