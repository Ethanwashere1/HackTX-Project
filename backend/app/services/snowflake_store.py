"""Snowflake as the matching store: it holds only event-member embeddings (ids + vector) and
answers cosine-similarity queries. Nothing else (chat, sessions, profiles) is ever sent here.

Reads run under a hard deadline of SNOWFLAKE_TIMEOUT_S; writes, which may also pay for the login,
a warehouse resume and the first CREATE TABLE, under SNOWFLAKE_WRITE_TIMEOUT_S. Every call raises
SnowflakeError on any failure, so callers can fall back to pgvector. One connection is reused per
process and dropped after an error.

A call that times out keeps running in its worker thread until the connector's own timeouts end
it; until then new calls fail fast instead of piling up behind it.

A failed sync leaves `event_members.snowflake_synced_at` behind `embedded_at`. sync_pending() pushes
those rows again; it runs after each successful sync and from the CLI:
`uv run python -m app.services.snowflake_store --backfill`.
"""

import argparse
import json
import logging
import math
import re
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import or_
from sqlmodel import Session, select, update

from app.config import EMBEDDING_DIM, get_settings, is_placeholder
from app.models import EventMember
from app.models.base import utcnow

log = logging.getLogger(__name__)

T = TypeVar("T")

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,254}$")
_VECTOR = f"VECTOR(FLOAT, {EMBEDDING_DIM})"
# Rows per MERGE: each vector is ~16 KB of JSON and Snowflake caps a statement at 1 MB.
MERGE_BATCH = 25
BACKFILL_LIMIT = 50  # rows per opportunistic sync_pending() call
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="snowflake")
_lock = threading.Lock()  # guards _conn and _table_ready; held while connecting
_conn: Any = None
_table_ready = False
_stuck_lock = threading.Lock()  # never held across I/O, so the busy check can't block
_stuck: set[Future] = set()  # calls that timed out but whose worker is still running


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
    # The connector's own limits end a worker whose call already timed out on our side.
    timeout = max(1, math.ceil(max(s.snowflake_timeout_s, s.snowflake_write_timeout_s)))
    params = {
        "account": s.snowflake_account,
        "user": s.snowflake_user,
        "password": s.snowflake_password,
        "warehouse": s.snowflake_warehouse,
        "database": s.snowflake_database,
        "schema": s.snowflake_schema,
        "login_timeout": timeout,
        "network_timeout": timeout,
        "session_parameters": {"STATEMENT_TIMEOUT_IN_SECONDS": timeout},
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


def _drop_connection() -> None:
    """Close and forget the cached connection (after an error)."""
    global _conn, _table_ready
    with _lock:
        conn, _conn, _table_ready = _conn, None, False
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def reset() -> None:
    """Drop the cached connection and forget calls that timed out (in tests)."""
    _drop_connection()
    with _stuck_lock:
        _stuck.clear()


def _busy() -> bool:
    """True while an earlier call that timed out is still running in its worker."""
    with _stuck_lock:
        _stuck.difference_update([f for f in _stuck if f.done()])
        return bool(_stuck)


def _run(fn: Callable[[Any], T], timeout: float | None = None) -> T:
    """Run fn(cursor) on the shared connection within `timeout` (default SNOWFLAKE_TIMEOUT_S)."""
    settings = get_settings()
    if not settings.snowflake_configured:
        raise SnowflakeError("Snowflake is not configured")
    timeout = settings.snowflake_timeout_s if timeout is None else timeout
    if _busy():
        raise SnowflakeError("Snowflake is still busy with a call that timed out")

    def work() -> T:
        try:
            cur = _connection().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except SnowflakeError:
            raise
        except Exception:
            _drop_connection()  # from the worker itself, never under a running call of its own
            raise

    future = _executor.submit(work)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout as exc:
        if not future.cancel():
            # Still running and can't be interrupted: leave its connection alone and fail fast
            # until it ends (the connector's login/network/statement timeouts bound how long).
            with _stuck_lock:
                _stuck.add(future)
        raise SnowflakeError(f"Snowflake timed out after {timeout}s") from exc
    except SnowflakeError:
        raise
    except Exception as exc:
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


def _merge_sql(table: str, n: int) -> str:
    """One MERGE of n rows from bound VALUES. An older vector never overwrites a newer one."""
    values = ", ".join(
        f"(%(id_{i})s, %(event_id_{i})s, %(user_id_{i})s, %(embedding_{i})s, %(embedded_at_{i})s)"
        for i in range(n)
    )
    return (
        f"MERGE INTO {table} t USING ("
        " SELECT column1 AS EVENT_MEMBER_ID, column2 AS EVENT_ID, column3 AS USER_ID,"
        f" PARSE_JSON(column4)::ARRAY::{_VECTOR} AS EMBEDDING,"
        " column5::TIMESTAMP_TZ AS EMBEDDED_AT"
        f" FROM VALUES {values}"
        ") s ON t.EVENT_MEMBER_ID = s.EVENT_MEMBER_ID"
        " WHEN MATCHED AND s.EMBEDDED_AT >= t.EMBEDDED_AT THEN UPDATE SET"
        " EVENT_ID = s.EVENT_ID, USER_ID = s.USER_ID, EMBEDDING = s.EMBEDDING,"
        " EMBEDDED_AT = s.EMBEDDED_AT"
        " WHEN NOT MATCHED THEN INSERT (EVENT_MEMBER_ID, EVENT_ID, USER_ID, EMBEDDING, EMBEDDED_AT)"
        " VALUES (s.EVENT_MEMBER_ID, s.EVENT_ID, s.USER_ID, s.EMBEDDING, s.EMBEDDED_AT)"
    )


def _merge_params(rows: list[EmbeddingRow]) -> dict[str, str]:
    params: dict[str, str] = {}
    for i, row in enumerate(rows):
        params.update({
            f"id_{i}": row.event_member_id,
            f"event_id_{i}": row.event_id,
            f"user_id_{i}": row.user_id,
            f"embedding_{i}": _vector_param(row.embedding),
            f"embedded_at_{i}": row.embedded_at.isoformat(),
        })
    return params


def upsert_embeddings(rows: list[EmbeddingRow]) -> None:
    """Insert or replace these members' vectors (an older vector never overwrites a newer one),
    MERGE_BATCH rows per statement, all within SNOWFLAKE_WRITE_TIMEOUT_S."""
    if not rows:
        return
    # A MERGE fails on duplicate source keys: keep each member's newest vector.
    latest: dict[str, EmbeddingRow] = {}
    for row in rows:
        seen = latest.get(row.event_member_id)
        if seen is None or row.embedded_at >= seen.embedded_at:
            latest[row.event_member_id] = row
    unique = list(latest.values())

    def work(cur: Any) -> None:
        table = _ensure_table(cur)
        for start in range(0, len(unique), MERGE_BATCH):
            chunk = unique[start:start + MERGE_BATCH]
            cur.execute(_merge_sql(table, len(chunk)), _merge_params(chunk))

    _run(work, get_settings().snowflake_write_timeout_s)
    log.info("Synced %d embedding(s) to Snowflake", len(unique))


def mark_synced(db: Session, rows: list[EmbeddingRow]) -> None:
    """Set snowflake_synced_at for these synced rows (not committed). A row re-embedded meanwhile
    is skipped: that run syncs its own vector."""
    now = utcnow()
    for row in rows:
        db.exec(
            update(EventMember)
            .where(EventMember.id == row.event_member_id, EventMember.embedded_at == row.embedded_at)
            .values(snowflake_synced_at=now)
        )


def pending_rows(db: Session, limit: int) -> list[EmbeddingRow]:
    """Up to `limit` embedded members whose current vector isn't in Snowflake yet, oldest first."""
    members = db.exec(
        select(EventMember.id, EventMember.event_id, EventMember.user_id, EventMember.embedding,
               EventMember.embedded_at)
        .where(
            EventMember.embedding.is_not(None),
            EventMember.embedded_at.is_not(None),
            or_(EventMember.snowflake_synced_at.is_(None),
                EventMember.snowflake_synced_at < EventMember.embedded_at),
        )
        .order_by(EventMember.embedded_at, EventMember.id)
        .limit(limit)
    ).all()
    return [
        EmbeddingRow(member_id, event_id, user_id, [float(v) for v in vector], embedded_at)
        for member_id, event_id, user_id, vector, embedded_at in members
    ]


def sync_pending(db: Session, limit: int = BACKFILL_LIMIT) -> int:
    """Push up to `limit` unsynced vectors to Snowflake and record it. Returns how many were sent.
    Raises SnowflakeError, and then records nothing."""
    rows = pending_rows(db, limit)
    db.rollback()  # no transaction held open during the Snowflake call
    if not rows:
        return 0
    upsert_embeddings(rows)
    mark_synced(db, rows)
    db.commit()
    return len(rows)


def delete_events(event_ids: list[str]) -> None:
    """Remove every vector of these events (used by the seed reset when events are deleted)."""
    if not event_ids:
        return

    def work(cur: Any) -> None:
        table = _ensure_table(cur)
        for event_id in event_ids:
            cur.execute(f"DELETE FROM {table} WHERE EVENT_ID = %(event_id)s", {"event_id": event_id})

    _run(work, get_settings().snowflake_write_timeout_s)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.snowflake_store",
        description="Push embeddings that never reached Snowflake (e.g. after a timeout).",
    )
    parser.add_argument("--backfill", action="store_true", required=True,
                        help="sync every embedded member whose vector isn't in Snowflake yet")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if not get_settings().snowflake_configured:
        print("Snowflake is not configured (SNOWFLAKE_*): nothing to sync.", file=sys.stderr)
        return 1
    from app import db as dbmod

    total = 0
    with Session(dbmod.get_engine()) as db:
        for _ in range(10_000):  # bounded, in case rows keep being re-embedded meanwhile
            try:
                sent = sync_pending(db, MERGE_BATCH)
            except SnowflakeError as exc:
                print(f"Synced {total} embedding(s), then Snowflake failed: {exc}", file=sys.stderr)
                return 1
            total += sent
            if sent < MERGE_BATCH:
                break
    print(f"Synced {total} embedding(s) to Snowflake")
    return 0


if __name__ == "__main__":
    sys.exit(main())
