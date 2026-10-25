"""Database engine and sessions.

If DATABASE_URL is unset or a placeholder, an embedded Postgres 16 + pgvector is started with
`pgserver` (data dir backend/.pgdata). It keeps running after the process exits so reloads are
fast; stop it with `uv run python -m app.devdb stop`.
"""

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlmodel import Session

from app.config import BACKEND_DIR, get_settings, is_placeholder

log = logging.getLogger(__name__)

PGDATA_DIR = BACKEND_DIR / ".pgdata"
EMBEDDED_DB = "squadup"
EMBEDDED_TEST_DB = "squadup_test"

_engine: Engine | None = None


def normalize_url(url: str) -> str:
    """Use the psycopg (v3) driver for any postgres URL."""
    for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache
def embedded_server():
    try:
        import pgserver
    except ImportError as exc:  # pragma: no cover - dev dependency missing
        raise RuntimeError(
            "DATABASE_URL is not set and the embedded Postgres (pgserver, a dev dependency) "
            "is not installed. Run `uv sync` or set DATABASE_URL."
        ) from exc
    PGDATA_DIR.mkdir(exist_ok=True)
    log.info("Starting embedded Postgres in %s", PGDATA_DIR)
    return pgserver.get_server(PGDATA_DIR, cleanup_mode=None)


def embedded_url(database: str) -> str:
    """Return a URL for `database` on the embedded server, creating the database if needed."""
    srv = embedded_server()
    admin = create_engine(normalize_url(srv.get_uri("postgres")), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": database}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        admin.dispose()
    return normalize_url(srv.get_uri(database))


def get_database_url() -> str:
    url = get_settings().database_url
    if is_placeholder(url):
        return embedded_url(EMBEDDED_DB)
    return normalize_url(url)


def get_test_database_url() -> str:
    url = get_settings().test_database_url
    if is_placeholder(url):
        return embedded_url(EMBEDDED_TEST_DB)
    return normalize_url(url)


def set_engine(url: str) -> Engine:
    """Point the app at a specific database (used by tests)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
