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
    "social_lookups",
}


def test_migrations_create_all_tables_and_pgvector(database_url):
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            assert EXPECTED_TABLES <= tables
            assert conn.execute(text("SELECT extname FROM pg_extension WHERE extname='vector'")).scalar() == "vector"
            dim = conn.execute(text(
                "SELECT atttypmod FROM pg_attribute"
                " WHERE attrelid = 'event_members'::regclass AND attname = 'embedding'"
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


def test_0002_moves_profiles_and_back(database_url):
    """0001 data (per-event profiles, socials on event_members) survives 0002 and its downgrade."""
    cfg = alembic_config(database_url)
    command.downgrade(cfg, "0001")
    engine = create_engine(database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO users (id, email, name, created_at, updated_at) VALUES"
                " ('usr_a', 'a@x.com', 'A', now(), now()), ('usr_b', 'b@x.com', 'B', now(), now());"
                "INSERT INTO events (id, host_id, name, description, type, tone, required_fields,"
                " interview_enabled, created_at) VALUES"
                " ('evt_1', 'usr_a', 'E1', '', 'informal', 'casual', '[]', false, now()),"
                " ('evt_2', 'usr_a', 'E2', '', 'informal', 'casual', '[]', false, now());"
                "INSERT INTO event_members (id, event_id, user_id, answers, fields, socials, joined_at)"
                " VALUES ('em_1', 'evt_1', 'usr_a', '{}', '{}',"
                "  '[{\"kind\": \"github\", \"value\": \"old\"}, {\"kind\": \"discord\", \"value\": \"a#1\"}]',"
                "  now() - interval '1 hour'),"
                " ('em_2', 'evt_2', 'usr_a', '{}', '{}', '[{\"kind\": \"github\", \"value\": \"new\"}]', now()),"
                " ('em_3', 'evt_1', 'usr_b', '{}', '{}', '[]', now());"
                "INSERT INTO profiles (id, event_id, user_id, summary, traits, transcript, profile_text,"
                " updated_at) VALUES"
                " ('prf_1', 'evt_1', 'usr_a', 'Summary A', '{}', '[]', 'text 1', now() - interval '1 hour'),"
                " ('prf_2', 'evt_2', 'usr_a', NULL, '{}', '[]', 'text 2', now())"
            ))
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            profiles = conn.execute(text(
                "SELECT user_id, id, summary, socials FROM profiles ORDER BY user_id")).all()
            assert [tuple(p) for p in profiles] == [
                ("usr_a", "prf_1", "Summary A",
                 [{"kind": "discord", "value": "a#1"}, {"kind": "github", "value": "new"}]),
                (profiles[1][0], profiles[1][1], None, []),
            ]
            assert profiles[1][0] == "usr_b"  # members without a profile get an empty one
            texts = dict(conn.execute(text("SELECT id, profile_text FROM event_members")).all())
            assert texts == {"em_1": "text 1", "em_2": "text 2", "em_3": ""}

        command.downgrade(cfg, "0001")
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT event_id, user_id, summary, profile_text FROM profiles ORDER BY event_id, user_id"
            )).all()
            assert [tuple(r) for r in rows] == [
                ("evt_1", "usr_a", "Summary A", "text 1"), ("evt_1", "usr_b", None, ""),
                ("evt_2", "usr_a", "Summary A", "text 2"),
            ]
            socials = conn.execute(text("SELECT socials FROM event_members WHERE id = 'em_2'")).scalar()
            assert socials == [{"kind": "discord", "value": "a#1"}, {"kind": "github", "value": "new"}]
    finally:
        command.upgrade(cfg, "head")
        engine.dispose()
