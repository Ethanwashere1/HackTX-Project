"""Snowflake as the matching store: it holds only event-member embeddings (ids + vector) and
answers cosine-similarity queries. Nothing else (chat, sessions, profiles) is ever sent here.

Every call runs under a hard deadline of SNOWFLAKE_TIMEOUT_S and raises SnowflakeError on any
failure, so callers can fall back to pgvector. One connection is reused per process and dropped
after an error.
"""

import json
import logging
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from app.config import EMBEDDING_DIM, get_settings, is_placeholder

log = logging.getLogger(__name__)

T = TypeVar("T")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,254}$")
_VECTOR = f"VECTOR(FLOAT, {EMBEDDING_DIM})"
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="snowflake")
_lock = threading.Lock()
_conn: Any = None
_table_ready = False


class SnowflakeError(Exception):
    """Snowflake is not configured, timed out or failed."""


@dataclass
class EmbeddingRow:
    event_member_id: str
    event_id: str
    user_id: str
    embedding: list[float]
    embedded_at: datetime


def table_name() -> str:
    name = get_settings().snowflake_table.strip()
    if not _IDENTIFIER.match(name):
        raise SnowflakeError("SNOWFLAKE_TABLE must be a plain identifier")
    return name


def _connect() -> Any:
    import snowflake.connector

    s = get_settings()
    timeout = max(1, int(s.snowflake_timeout_s))
    params = {
        "account": s.snowflake_account,
        "user": s.snowflake_user,
        "password": s.snowflake_password,
        "warehouse": s.snowflake_warehouse,
        "database": s.snowflake_database,
        "schema": s.snowflake_schema,
        "login_timeout": timeout,
        "network_timeout": timeout,
        "application": "SquadUp",
    }
    if not is_placeholder(s.snowflake_role):
        params["role"] = s.snowflake_role
    return snowflake.connector.connect(**params)


def _connection() -> Any:
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        return _conn


def reset() -> None:
    """Drop the cached connection (after an error, and in tests)."""
    global _conn, _table_ready
    with _lock:
        conn, _conn, _table_ready = _conn, None, False
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _run(fn: Callable[[Any], T]) -> T:
    """Run fn(cursor) on the shared connection within SNOWFLAKE_TIMEOUT_S."""
    settings = get_settings()
    if not settings.snowflake_configured:
        raise SnowflakeError("Snowflake is not configured")

    def work() -> T:
        cur = _connection().cursor()
        try:
            return fn(cur)
        finally:
            cur.close()

    future = _executor.submit(work)
    try:
        return future.result(timeout=settings.snowflake_timeout_s)
    except FutureTimeout as exc:
        future.cancel()
        reset()
        raise SnowflakeError(f"Snowflake timed out after {settings.snowflake_timeout_s}s") from exc
    except SnowflakeError:
        raise
    except Exception as exc:
        reset()
        raise SnowflakeError(f"Snowflake call failed: {exc.__class__.__name__}: {exc}") from exc


def _ensure_table(cur: Any) -> str:
    global _table_ready
    table = table_name()
    if not _table_ready:
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            " EVENT_MEMBER_ID VARCHAR(40) NOT NULL PRIMARY KEY,"
            " EVENT_ID VARCHAR(40) NOT NULL,"
            " USER_ID VARCHAR(40) NOT NULL,"
            f" EMBEDDING {_VECTOR} NOT NULL,"
            " EMBEDDED_AT TIMESTAMP_TZ NOT NULL)"
        )
        _table_ready = True
    return table


def _vector_param(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def upsert_embeddings(rows: list[EmbeddingRow]) -> None:
    """Insert or replace these members' vectors (an older vector never overwrites a newer one)."""
    if not rows:
        return

    def work(cur: Any) -> None:
        table = _ensure_table(cur)
        sql = (
            f"MERGE INTO {table} t USING ("
            " SELECT %(id)s AS EVENT_MEMBER_ID, %(event_id)s AS EVENT_ID, %(user_id)s AS USER_ID,"
            f" PARSE_JSON(%(embedding)s)::ARRAY::{_VECTOR} AS EMBEDDING,"
            " %(embedded_at)s::TIMESTAMP_TZ AS EMBEDDED_AT"
            ") s ON t.EVENT_MEMBER_ID = s.EVENT_MEMBER_ID"
            " WHEN MATCHED AND s.EMBEDDED_AT >= t.EMBEDDED_AT THEN UPDATE SET"
            " EVENT_ID = s.EVENT_ID, USER_ID = s.USER_ID, EMBEDDING = s.EMBEDDING,"
            " EMBEDDED_AT = s.EMBEDDED_AT"
            " WHEN NOT MATCHED THEN INSERT (EVENT_MEMBER_ID, EVENT_ID, USER_ID, EMBEDDING, EMBEDDED_AT)"
            " VALUES (s.EVENT_MEMBER_ID, s.EVENT_ID, s.USER_ID, s.EMBEDDING, s.EMBEDDED_AT)"
        )
        for row in rows:
            cur.execute(
                sql,
                {
                    "id": row.event_member_id,
                    "event_id": row.event_id,
                    "user_id": row.user_id,
                    "embedding": _vector_param(row.embedding),
                    "embedded_at": row.embedded_at.isoformat(),
                },
            )

    _run(work)
    log.info("Synced %d embedding(s) to Snowflake", len(rows))


def delete_events(event_ids: list[str]) -> None:
    """Remove every vector of these events (used by the seed reset when events are deleted)."""
    if not event_ids:
        return

    def work(cur: Any) -> None:
        table = _ensure_table(cur)
        for event_id in event_ids:
            cur.execute(f"DELETE FROM {table} WHERE EVENT_ID = %(event_id)s", {"event_id": event_id})

    _run(work)


def similarities(event_id: str, vector: list[float], exclude_user_id: str, limit: int) -> dict[str, float]:
    """{user_id: cosine similarity to `vector`} for the event's synced members, best first."""

    def work(cur: Any) -> dict[str, float]:
        table = _ensure_table(cur)
        cur.execute(
            f"SELECT USER_ID, VECTOR_COSINE_SIMILARITY(EMBEDDING,"
            f" PARSE_JSON(%(vector)s)::ARRAY::{_VECTOR}) AS SIM"
            f" FROM {table} WHERE EVENT_ID = %(event_id)s AND USER_ID <> %(viewer)s"
            " ORDER BY SIM DESC LIMIT %(limit)s",
            {"vector": _vector_param(vector), "event_id": event_id,
             "viewer": exclude_user_id, "limit": int(limit)},
        )
        return {str(user_id): float(sim) for user_id, sim in cur.fetchall() if sim is not None}

    return _run(work)
