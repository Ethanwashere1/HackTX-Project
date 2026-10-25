"""Profile embeddings (Gemini, mocked) into pgvector and the Snowflake sync (fake connector)."""

import hashlib
import math
import time
from datetime import timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app import db as dbmod
from app.config import EMBEDDING_DIM, get_settings
from app.models import EventMember
from app.models.base import utcnow
from app.services import embeddings, profiles, snowflake_store
from tests.test_events import create, informal

REAL_CONNECT = snowflake_store._connect


# --- fakes ---------------------------------------------------------------------------------------

def text_vector(text: str) -> list[float]:
    """A deterministic, unnormalized 768-dim vector for a text."""
    digest = hashlib.sha256(text.encode()).digest()
    vec = [0.0] * EMBEDDING_DIM
    for i, b in enumerate(digest):
        vec[(b * 7 + i) % EMBEDDING_DIM] += 1 + b / 255
    return vec


class FakeGemini:
    """Stands in for embeddings._post; records each batchEmbedContents call."""

    def __init__(self, respond=None):
        self.calls: list[dict] = []
        self.respond = respond

    def __call__(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.respond is not None:
            return self.respond(url, json)
        values = [{"values": text_vector(r["content"]["parts"][0]["text"])} for r in json["requests"]]
        return httpx.Response(200, json={"embeddings": values}, request=httpx.Request("POST", url))

    @property
    def texts(self) -> list[str]:
        return [r["content"]["parts"][0]["text"] for c in self.calls for r in c["json"]["requests"]]


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows: list = []

    def execute(self, sql, params=None):
        self.conn.executed.append((" ".join(sql.split()), params))
        if self.conn.delay:
            time.sleep(self.conn.delay)
        if self.conn.fail:
            raise RuntimeError("snowflake exploded")
        self.rows = list(self.conn.rows) if sql.lstrip().startswith("SELECT") else []

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeSnowflake:
    """Stands in for the connector connection (snowflake_store._connect)."""

    def __init__(self, rows=(), fail=False, delay=0.0):
        self.executed: list[tuple[str, dict | None]] = []
        self.rows, self.fail, self.delay = list(rows), fail, delay
        self.connects = self.closes = 0

    def connect(self):
        self.connects += 1
        return self

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closes += 1

    def statements(self, prefix: str) -> list[tuple[str, dict | None]]:
        return [(sql, p) for sql, p in self.executed if sql.startswith(prefix)]


def gemini_on(monkeypatch, fake: FakeGemini | None = None) -> FakeGemini:
    fake = fake or FakeGemini()
    monkeypatch.setattr(get_settings(), "gemini_api_key", "test-gemini-key")
    monkeypatch.setattr(embeddings, "_post", fake)
    return fake


def snowflake_on(monkeypatch, fake: FakeSnowflake | None = None, timeout: float = 5) -> FakeSnowflake:
    fake = fake or FakeSnowflake()
    s = get_settings()
    for key in ("account", "user", "password", "warehouse", "database", "schema"):
        monkeypatch.setattr(s, f"snowflake_{key}", f"test-{key}")
    monkeypatch.setattr(s, "snowflake_timeout_s", timeout)
    monkeypatch.setattr(snowflake_store, "_connect", fake.connect)
    return fake


@pytest.fixture(autouse=True)
def _fresh_snowflake():
    snowflake_store.reset()
    yield
    snowflake_store.reset()


def no_network(*args, **kwargs):
    raise AssertionError("no external call expected")


def members(event_id: str) -> list[EventMember]:
    with Session(dbmod.get_engine()) as db:
        return list(db.exec(select(EventMember).where(EventMember.event_id == event_id)
                            .order_by(EventMember.joined_at)).all())


def joined_event(login_as, n: int = 1, **event) -> str:
    host = login_as("host@x.com", "Host")
    event_id = create(host, informal(**event))
    for i in range(n):
        c = login_as(f"user{i}@x.com", f"User {i}")
        assert c.post(f"/api/events/{event_id}/join", json={}).status_code == 201
    return event_id


# --- the hook ------------------------------------------------------------------------------------

def test_not_configured_skips_and_leaves_embedding_null(login_as, monkeypatch):
    monkeypatch.setattr(embeddings, "_post", no_network)
    event_id = joined_event(login_as)
    (m,) = members(event_id)
    assert m.profile_text and m.embedding is None and m.embedded_at is None


def test_join_embeds_profile_text(login_as, monkeypatch):
    gemini = gemini_on(monkeypatch)
    event_id = joined_event(login_as)
    (m,) = members(event_id)
    assert m.embedding is not None and len(m.embedding) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(v * v for v in m.embedding)), 1.0, rel_tol=1e-5)
    assert m.embedded_at is not None and m.snowflake_synced_at is None  # Snowflake is off

    (call,) = gemini.calls
    assert call["url"].endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert call["headers"] == {"x-goog-api-key": "test-gemini-key"}
    assert call["timeout"] == get_settings().gemini_timeout_s
    (req,) = call["json"]["requests"]
    assert req["model"] == "models/gemini-embedding-001"
    assert req["outputDimensionality"] == 768 and req["taskType"] == "SEMANTIC_SIMILARITY"
    assert gemini.texts == [m.profile_text]


def test_profile_change_re_embeds(login_as, monkeypatch, db):
    gemini = gemini_on(monkeypatch)
    event_id = joined_event(login_as)
    (before,) = members(event_id)
    profile = profiles.get_or_create_profile(db, before.user_id)
    profile.summary = "Backend dev who wants to win"
    db.add(profile)
    db.commit()
    profiles.refresh_member_texts(db, before.user_id)
    (after,) = members(event_id)
    assert "Backend dev who wants to win" in gemini.texts[-1] == after.profile_text
    assert after.embedding != before.embedding and after.embedded_at > before.embedded_at


def _respond(status=200, body=None, raise_exc=None):
    def respond(url, json):
        if raise_exc:
            raise raise_exc
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))
    return respond


@pytest.mark.parametrize(
    "respond",
    [
        _respond(500, {"error": {"message": "boom"}}),
        _respond(raise_exc=httpx.ReadTimeout("slow")),
        _respond(200, {"embeddings": [{"values": [0.1] * 3072}]}),  # wrong dimension
        _respond(200, {"embeddings": [{"values": [0.0] * EMBEDDING_DIM}]}),  # zero vector
        _respond(200, {"unexpected": True}),
        _respond(200, {"embeddings": []}),  # count mismatch
    ],
    ids=["http_500", "timeout", "wrong_dim", "zero", "bad_body", "missing"],
)
def test_gemini_failure_leaves_embedding_null_and_join_succeeds(login_as, monkeypatch, respond):
    gemini = gemini_on(monkeypatch, FakeGemini(respond))
    event_id = joined_event(login_as)  # asserts the join's 201
    (m,) = members(event_id)
    assert len(gemini.calls) == 1 and m.embedding is None and m.embedded_at is None


def test_text_changed_during_embedding_is_not_stored(login_as, monkeypatch):
    event_id = joined_event(login_as)
    (m,) = members(event_id)

    def change_text_mid_call(url, json):
        with Session(dbmod.get_engine()) as other:
            row = other.get(EventMember, m.id)
            row.profile_text = row.profile_text + "\nNewer text"
            other.add(row)
            other.commit()
        values = [{"values": text_vector("x")}]
        return httpx.Response(200, json={"embeddings": values}, request=httpx.Request("POST", url))

    gemini_on(monkeypatch, FakeGemini(change_text_mid_call))
    embeddings.embed_members([m.id])
    (after,) = members(event_id)
    assert after.profile_text.endswith("Newer text") and after.embedding is None


def test_embed_members_never_raises(monkeypatch):
    gemini_on(monkeypatch)
    monkeypatch.setattr(embeddings, "_embed_and_store", lambda ids: 1 / 0)
    embeddings.embed_members(["em_x"])  # logged, not raised
    embeddings.embed_members([])


# --- Snowflake sync ------------------------------------------------------------------------------

def test_join_syncs_to_snowflake(login_as, monkeypatch):
    gemini_on(monkeypatch)
    sf = snowflake_on(monkeypatch)
    event_id = joined_event(login_as, n=2)
    m1, m2 = members(event_id)
    assert m1.snowflake_synced_at is not None and m2.snowflake_synced_at is not None

    creates = sf.statements("CREATE TABLE IF NOT EXISTS SQUADUP_EMBEDDINGS")
    merges = sf.statements("MERGE INTO SQUADUP_EMBEDDINGS")
    assert len(creates) == 1 and sf.connects == 1  # table check and connection are reused
    assert "VECTOR(FLOAT, 768)" in creates[0][0]
    assert [p["id_0"] for _, p in merges] == [m1.id, m2.id]  # one join, one embedding, one MERGE
    params = merges[0][1]
    assert set(params) == {"id_0", "event_id_0", "user_id_0", "embedding_0", "embedded_at_0"}  # no PII
    assert (params["event_id_0"], params["user_id_0"]) == (event_id, m1.user_id)
    assert len(params["embedding_0"].strip("[]").split(",")) == EMBEDDING_DIM
    assert "PARSE_JSON(column4)::ARRAY::VECTOR(FLOAT, 768)" in merges[0][0]
    assert "FROM VALUES (%(id_0)s, %(event_id_0)s, %(user_id_0)s, %(embedding_0)s, %(embedded_at_0)s))" in merges[0][0]
    assert "WHEN MATCHED AND s.EMBEDDED_AT >= t.EMBEDDED_AT" in merges[0][0]


def _row(i: int, at=None) -> snowflake_store.EmbeddingRow:
    return snowflake_store.EmbeddingRow(f"em_{i:03}", "evt_1", f"usr_{i:03}", [0.1] * EMBEDDING_DIM,
                                        at or utcnow())


def test_upsert_batches_rows_into_few_merges(monkeypatch):
    sf = snowflake_on(monkeypatch)
    older = _row(0, utcnow() - timedelta(minutes=5))
    rows = [older] + [_row(i) for i in range(30)]  # em_000 twice: only the newer vector is sent
    snowflake_store.upsert_embeddings(rows)
    merges = sf.statements("MERGE INTO SQUADUP_EMBEDDINGS")
    assert [len(p) for _, p in merges] == [25 * 5, 5 * 5]  # MERGE_BATCH rows per statement
    sent = {p[f"id_{i}"]: p[f"embedded_at_{i}"] for _, p in merges for i in range(len(p) // 5)}
    assert len(sent) == 30 and sent["em_000"] == rows[1].embedded_at.isoformat()
    assert merges[1][0].count("(%(id_") == 5


def test_writes_get_the_longer_write_deadline(monkeypatch):
    sf = snowflake_on(monkeypatch, FakeSnowflake(delay=0.3), timeout=0.1)
    monkeypatch.setattr(get_settings(), "snowflake_write_timeout_s", 5)
    snowflake_store.upsert_embeddings([_row(1)])  # CREATE + MERGE take 0.6 s: fine for a write
    assert len(sf.statements("MERGE")) == 1


def test_a_timed_out_call_blocks_new_calls_until_it_ends(monkeypatch):
    sf = snowflake_on(monkeypatch, FakeSnowflake(delay=0.5), timeout=0.1)
    with pytest.raises(snowflake_store.SnowflakeError, match="timed out"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)
    assert sf.closes == 0  # the running call's connection is left alone
    executed = len(sf.executed)
    with pytest.raises(snowflake_store.SnowflakeError, match="still busy"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)
    assert len(sf.executed) == executed  # failed fast, nothing queued behind the stuck call

    for future in list(snowflake_store._stuck):
        future.result(timeout=5)
    sf.delay = 0
    assert snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5) == {}
    assert sf.connects == 1  # the connection survived the timeout


def test_connector_timeouts_end_a_stuck_worker(monkeypatch):
    import snowflake.connector

    calls = []
    snowflake_on(monkeypatch)
    monkeypatch.setattr(snowflake_store, "_connect", REAL_CONNECT)
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kw: calls.append(kw) or FakeSnowflake())
    monkeypatch.setattr(get_settings(), "snowflake_write_timeout_s", 30)
    snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)
    (params,) = calls
    assert params["login_timeout"] == params["network_timeout"] == 30
    assert params["session_parameters"] == {"STATEMENT_TIMEOUT_IN_SECONDS": 30}


def test_failed_sync_is_backfilled_after_the_next_good_one(login_as, monkeypatch, db):
    gemini_on(monkeypatch)
    snowflake_on(monkeypatch, FakeSnowflake(fail=True))
    event_id = joined_event(login_as)
    (m1,) = members(event_id)
    assert m1.embedding is not None and m1.snowflake_synced_at is None

    sf = snowflake_on(monkeypatch, FakeSnowflake())
    c = login_as("late@x.com", "Late")
    assert c.post(f"/api/events/{event_id}/join", json={}).status_code == 201
    m1, m2 = members(event_id)
    assert m1.snowflake_synced_at is not None and m2.snowflake_synced_at is not None
    merges = sf.statements("MERGE")
    assert [p["id_0"] for _, p in merges] == [m2.id, m1.id]  # the new sync, then the backfill
    assert snowflake_store.pending_rows(db, 10) == []


def test_re_embedded_rows_are_pending_again(login_as, monkeypatch, db):
    gemini_on(monkeypatch)
    snowflake_on(monkeypatch)
    event_id = joined_event(login_as)
    (m,) = members(event_id)
    assert m.snowflake_synced_at is not None
    assert snowflake_store.pending_rows(db, 10) == []
    row = db.get(EventMember, m.id)
    row.embedded_at = m.snowflake_synced_at + timedelta(seconds=1)  # embedded after the last sync
    db.add(row)
    db.commit()
    (pending,) = snowflake_store.pending_rows(db, 10)
    assert pending.event_member_id == m.id and len(pending.embedding) == EMBEDDING_DIM


def test_backfill_cli(login_as, monkeypatch, capsys):
    gemini_on(monkeypatch)
    snowflake_on(monkeypatch, FakeSnowflake(fail=True))
    event_id = joined_event(login_as, n=3)
    assert all(m.snowflake_synced_at is None for m in members(event_id))

    sf = snowflake_on(monkeypatch, FakeSnowflake())
    assert snowflake_store.main(["--backfill"]) == 0
    assert "Synced 3 embedding(s) to Snowflake" in capsys.readouterr().out
    assert all(m.snowflake_synced_at is not None for m in members(event_id))
    (merge,) = sf.statements("MERGE")
    assert len(merge[1]) == 3 * 5  # one statement for all three

    snowflake_on(monkeypatch, FakeSnowflake(fail=True))
    assert snowflake_store.main(["--backfill"]) == 0  # nothing pending: no Snowflake call
    for key in ("account", "user"):
        monkeypatch.setattr(get_settings(), f"snowflake_{key}", "REPLACE_ME")
    assert snowflake_store.main(["--backfill"]) == 1
    assert "not configured" in capsys.readouterr().err


def test_snowflake_sync_failure_keeps_embedding(login_as, monkeypatch):
    gemini_on(monkeypatch)
    snowflake_on(monkeypatch, FakeSnowflake(fail=True))
    event_id = joined_event(login_as)
    (m,) = members(event_id)
    assert m.embedding is not None and m.snowflake_synced_at is None


def test_snowflake_not_configured_is_skipped(login_as, monkeypatch):
    gemini_on(monkeypatch)
    monkeypatch.setattr(snowflake_store, "_connect", no_network)
    event_id = joined_event(login_as)
    (m,) = members(event_id)
    assert m.embedding is not None and m.snowflake_synced_at is None


def test_snowflake_similarities_query(monkeypatch):
    sf = snowflake_on(monkeypatch, FakeSnowflake(rows=[("usr_b", 0.9), ("usr_c", 0.4), ("usr_d", None)]))
    result = snowflake_store.similarities("evt_1", [0.5] * EMBEDDING_DIM, "usr_a", 50)
    assert result == {"usr_b": 0.9, "usr_c": 0.4}
    (sql, params) = sf.statements("SELECT")[0]
    assert "VECTOR_COSINE_SIMILARITY(EMBEDDING, PARSE_JSON(%(vector)s)::ARRAY::VECTOR(FLOAT, 768))" in sql
    assert "WHERE EVENT_ID = %(event_id)s AND USER_ID <> %(viewer)s ORDER BY SIM DESC LIMIT %(limit)s" in sql
    assert (params["event_id"], params["viewer"], params["limit"]) == ("evt_1", "usr_a", 50)


def test_snowflake_errors_and_timeouts_raise_snowflake_error(monkeypatch):
    snowflake_on(monkeypatch, FakeSnowflake(fail=True))
    with pytest.raises(snowflake_store.SnowflakeError, match="failed"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)
    snowflake_on(monkeypatch, FakeSnowflake(delay=1.0), timeout=0.1)
    with pytest.raises(snowflake_store.SnowflakeError, match="timed out"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)


def test_snowflake_rejects_unsafe_table_name(monkeypatch):
    snowflake_on(monkeypatch)
    monkeypatch.setattr(get_settings(), "snowflake_table", "X; DROP TABLE Y")
    with pytest.raises(snowflake_store.SnowflakeError, match="SNOWFLAKE_TABLE"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)


def test_snowflake_not_configured_raises(monkeypatch):
    monkeypatch.setattr(snowflake_store, "_connect", no_network)
    with pytest.raises(snowflake_store.SnowflakeError, match="not configured"):
        snowflake_store.similarities("evt_1", [1.0] * EMBEDDING_DIM, "usr_a", 5)
