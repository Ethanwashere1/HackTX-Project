from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

from app.config import EMBEDDING_DIM
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "users", "contact_methods", "user_sessions", "interview_tokens", "orgs", "org_members",
    "org_roster_entries", "events", "questions", "event_members", "profiles", "threads",
    "thread_participants", "messages", "groups", "group_members", "requests", "connections",
}


def test_migrations_create_all_tables_and_pgvector(database_url):
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert EXPECTED_TABLES <= tables
            assert conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
            dim = conn.execute(text(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'profiles'::regclass AND attname = 'embedding'"
            )).scalar()
            assert dim == EMBEDDING_DIM == 768
            # The vector type and distance operator work.
            assert conn.execute(text("SELECT '[1,0]'::vector <=> '[1,0]'::vector")).scalar() == 0
    finally:
        engine.dispose()


def test_models_match_migrations(database_url):
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
        assert diff == [], f"Models differ from migrations; add a migration: {diff}"
    finally:
        engine.dispose()


def test_downgrade_and_upgrade_round_trip(database_url):
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            assert EXPECTED_TABLES <= set(inspect(conn).get_table_names())
    finally:
        engine.dispose()
