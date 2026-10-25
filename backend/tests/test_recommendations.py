"""Contract section 4: GET /api/events/{id}/recommendations, its exclusions and every fallback
(Snowflake -> pgvector, agents rerank -> similarity order). Gemini, Snowflake and agents are mocked."""

import math

import httpx
import pytest
from sqlmodel import Session, select, update

from app import db as dbmod
from app.config import EMBEDDING_DIM, get_settings
from app.models import EventMember, OrgMember, Profile
from app.services import agents_client, snowflake_store
from tests.test_embeddings import FakeGemini, FakeSnowflake, gemini_on, snowflake_on
from tests.test_events import make_org
from tests.test_health_errors import assert_error
from tests.test_requests import accept_ok, form_group, join, make_event, send_ok, uid


# --- helpers -------------------------------------------------------------------------------------

def vec(**weights: float) -> list[float]:
    """vec(d0=1, d1=0.5): a 768-dim vector with those dimensions set."""
    v = [0.0] * EMBEDDING_DIM
    for key, w in weights.items():
        v[int(key[1:])] = w
    return v


def cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def set_embedding(event_id: str, client, vector: list[float] | None) -> None:
    with Session(dbmod.get_engine()) as db:
        db.exec(update(EventMember)
                .where(EventMember.event_id == event_id, EventMember.user_id == uid(client))
                .values(embedding=vector))
        db.commit()


def setup_event(login_as, names, *, type="structured", **settings):
    host = login_as("host@x.com", "Hannah Host")
    event_id = make_event(host, type=type, **settings)
    users = {n: login_as(f"{n}@x.com", n.capitalize()) for n in names}
    for c in users.values():
        join(c, event_id)
    return event_id, users


def recs(client, event_id, **params) -> dict:
    resp = client.get(f"/api/events/{event_id}/recommendations", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def people_ids(body) -> list[str]:
    return [p["user_id"] for p in body["people"]]


def group_ids(body) -> list[str]:
    return [g["group_id"] for g in body["groups"]]


class FakeAgents:
    """Stands in for agents_client._post (POST /recommend)."""

    def __init__(self, results=None, status=200, exc=None, body=None):
        self.results, self.status, self.exc, self.body = results, status, exc, body
        self.calls: list[dict] = []

    def __call__(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        request = httpx.Request("POST", url)
        if self.body is not None:
            return httpx.Response(self.status, content=self.body, request=request)
        results = self.results(json) if callable(self.results) else self.results
        return httpx.Response(self.status, json={"results": results}, request=request)


@pytest.fixture(autouse=True)
def agents(monkeypatch) -> FakeAgents:
    """The agents service is down unless a test installs its own FakeAgents."""
    fake = FakeAgents(exc=httpx.ConnectError("agents down"))
    monkeypatch.setattr(agents_client, "_post", fake)
    snowflake_store.reset()
    yield fake
    snowflake_store.reset()


def use_agents(monkeypatch, fake: FakeAgents) -> FakeAgents:
    monkeypatch.setattr(agents_client, "_post", fake)
    return fake


@pytest.fixture
def ranked(login_as):
    """ana (viewer) plus ben, cara, dan with known similarity to her, and eve without a vector."""
    event_id, u = setup_event(login_as, ["ana", "ben", "cara", "dan", "eve"])
    vectors = {"ana": vec(d0=1), "ben": vec(d0=0.9, d1=0.1), "cara": vec(d0=0.5, d1=0.5), "dan": vec(d1=1)}
    for name, v in vectors.items():
        set_embedding(event_id, u[name], v)
    return event_id, u, vectors


# --- access --------------------------------------------------------------------------------------

def test_requires_login(client):
    assert_error(client.get("/api/events/evt_x/recommendations"), 401, "unauthenticated")


def test_unknown_event_non_member_and_bad_limit(login_as):
    event_id, u = setup_event(login_as, ["ana"])
    outsider = login_as("out@x.com", "Out")
    assert_error(outsider.get("/api/events/evt_nope/recommendations"), 404, "not_found")
    assert_error(outsider.get(f"/api/events/{event_id}/recommendations"), 403, "forbidden")
    for bad in (0, 51, "x"):
        assert_error(u["ana"].get(f"/api/events/{event_id}/recommendations", params={"limit": bad}),
                     422, "validation_error")


def test_org_event_needs_approved_membership(login_as, db):
    host, ana = login_as("host@x.com", "Host"), login_as()
    org_id = make_org(db, {uid(host): "approved", uid(ana): "approved"})
    event_id = make_event(host, org_id=org_id)
    join(ana, event_id)
    db.exec(update(OrgMember).where(OrgMember.user_id == uid(ana)).values(status="pending"))
    db.commit()
    assert_error(ana.get(f"/api/events/{event_id}/recommendations"), 403, "not_org_member")


# --- similarity order (pgvector) and the response shape -----------------------------------------

def test_pgvector_similarity_order_when_snowflake_off_and_agents_down(ranked, agents, monkeypatch):
    event_id, u, v = ranked
    with Session(dbmod.get_engine()) as db:
        db.exec(update(Profile).where(Profile.user_id == uid(u["ben"])).values(summary="Backend dev"))
        db.commit()
    monkeypatch.setattr(snowflake_store, "_connect", lambda: pytest.fail("Snowflake is off"))
    body = recs(u["ana"], event_id)

    assert body["ranked_by"] == "similarity" and body["groups"] == []
    assert people_ids(body) == [uid(u[n]) for n in ("ben", "cara", "dan", "eve")]  # eve: no vector
    ben = body["people"][0]
    assert ben == {"user_id": uid(u["ben"]), "name": "Ben", "summary": "Backend dev",
                   "score": round(cos(v["ana"], v["ben"]), 4), "reason": None}
    assert [p["score"] for p in body["people"][1:]] == [round(cos(v["ana"], v["cara"]), 4), 0.0, 0.0]
    assert len(agents.calls) == 1  # tried, failed, fell back


def test_limit_applies_per_type(ranked):
    event_id, u, _ = ranked
    assert people_ids(recs(u["ana"], event_id, limit=2)) == [uid(u["ben"]), uid(u["cara"])]


def test_viewer_without_embedding_still_gets_candidates(ranked):
    event_id, u, _ = ranked
    set_embedding(event_id, u["ana"], None)  # Gemini is off, so it stays null
    body = recs(u["ana"], event_id)
    assert body["ranked_by"] == "similarity"
    assert people_ids(body) == [uid(u[n]) for n in ("ben", "cara", "dan", "eve")]  # join order
    assert {p["score"] for p in body["people"]} == {0.0}


def test_viewer_without_embedding_is_embedded_on_the_fly(ranked, monkeypatch):
    event_id, u, _ = ranked
    set_embedding(event_id, u["ana"], None)

    def respond(url, json):  # ana's text embeds close to dan
        values = [{"values": vec(d1=1, d0=0.05)} for _ in json["requests"]]
        return httpx.Response(200, json={"embeddings": values}, request=httpx.Request("POST", url))

    gemini = gemini_on(monkeypatch, FakeGemini(respond))
    body = recs(u["ana"], event_id)
    assert len(gemini.calls) == 1
    assert people_ids(body)[0] == uid(u["dan"])


def test_open_groups_are_scored_by_member_similarity(ranked):
    event_id, u, v = ranked
    group_id = form_group(u["cara"], u["dan"], event_id)
    body = recs(u["ana"], event_id)
    (group,) = body["groups"]
    expected = round((cos(v["ana"], v["cara"]) + cos(v["ana"], v["dan"])) / 2, 4)
    assert group == {
        "group_id": group_id, "name": group["name"], "size": 2, "max_size": 4,
        "members": [{"user_id": uid(u["cara"]), "name": "Cara"}, {"user_id": uid(u["dan"]), "name": "Dan"}],
        "score": expected, "reason": None,
    }
    assert group["name"].startswith("Team ")
    # Members of other groups are still recommended as people (contract section 4).
    assert set(people_ids(body)) == {uid(u[n]) for n in ("ben", "cara", "dan", "eve")}


# --- exclusions ----------------------------------------------------------------------------------

def test_exclusions(login_as):
    names = ["ana", "ben", "cara", "dan", "eve", "fay", "gus", "hal", "ivy", "jon", "kim", "lee", "max"]
    event_id, u = setup_event(login_as, names, max_size=3, group_count=10, max_groups_per_user=2)
    ana = u["ana"]
    g1 = form_group(ana, u["ben"], event_id)  # ana's own group: ben is a group-mate
    g2 = form_group(u["cara"], u["dan"], event_id)
    accept_ok(u["cara"], send_ok(u["eve"], event_id, g2, "group")["request_id"])  # g2 is now full
    g3 = form_group(u["fay"], u["gus"], event_id)  # open
    g4 = form_group(u["lee"], u["max"], event_id)
    send_ok(ana, event_id, g4, "group")  # pending request from ana to g4
    declined = send_ok(ana, event_id, uid(u["hal"]))  # hal declined ana
    assert u["hal"].post(f"/api/requests/{declined['request_id']}/decline").status_code == 200
    send_ok(u["ivy"], event_id, uid(ana))  # pending, ivy -> ana
    send_ok(ana, event_id, uid(u["jon"]))  # pending, ana -> jon

    body = recs(ana, event_id)
    assert set(people_ids(body)) == {uid(u[n]) for n in ("cara", "dan", "eve", "fay", "gus", "kim", "lee", "max")}
    assert group_ids(body) == [g3]
    assert g1 not in group_ids(body) and g2 not in group_ids(body) and g4 not in group_ids(body)

    # From hal's side the decline excludes ana too.
    assert uid(ana) not in people_ids(recs(u["hal"], event_id))


def test_requests_to_viewers_group_and_declined_groups_are_excluded(login_as):
    event_id, u = setup_event(login_as, ["ana", "ben", "cara", "dan", "eve"], max_groups_per_user=2)
    g1 = form_group(u["ana"], u["ben"], event_id)
    g2 = form_group(u["cara"], u["dan"], event_id)
    send_ok(u["eve"], event_id, g1, "group")  # eve wants to join ana's group: pending
    req = send_ok(u["ana"], event_id, g2, "group")
    assert u["cara"].post(f"/api/requests/{req['request_id']}/decline").status_code == 200
    body = recs(u["ana"], event_id)
    assert uid(u["eve"]) not in people_ids(body)
    assert body["groups"] == []  # g1 is ana's, g2 declined her


def test_no_groups_once_viewer_reached_max_groups_per_user(ranked):
    event_id, u, _ = ranked
    form_group(u["ana"], u["ben"], event_id)  # max_groups_per_user is 1
    form_group(u["cara"], u["dan"], event_id)
    body = recs(u["ana"], event_id)
    assert body["groups"] == []
    assert people_ids(body) == [uid(u[n]) for n in ("cara", "dan", "eve")]


def test_informal_event_has_no_groups_and_excludes_connections(login_as):
    event_id, u = setup_event(login_as, ["ana", "ben", "cara"], type="informal")
    accept_ok(u["ana"], send_ok(u["ben"], event_id, uid(u["ana"]))["request_id"])
    body = recs(u["ana"], event_id)
    assert body["groups"] == [] and people_ids(body) == [uid(u["cara"])]


def test_alone_in_event_returns_empty_lists(login_as, agents):
    event_id, u = setup_event(login_as, ["ana"])
    assert recs(u["ana"], event_id) == {"ranked_by": "similarity", "people": [], "groups": []}
    assert agents.calls == []  # nothing to rerank


# --- Snowflake similarity and its fallback ---------------------------------------------------------

def test_snowflake_similarity_is_used_when_configured(ranked, monkeypatch):
    event_id, u, v = ranked
    snowflake_on(monkeypatch)
    calls = []

    def fake_similarities(ev, vector, viewer_id, limit):
        calls.append((ev, vector, viewer_id))
        return {uid(u["dan"]): 0.95, uid(u["cara"]): 0.5}  # ben not synced yet

    monkeypatch.setattr(snowflake_store, "similarities", fake_similarities)
    body = recs(u["ana"], event_id)
    assert calls == [(event_id, v["ana"], uid(u["ana"]))]
    assert people_ids(body) == [uid(u[n]) for n in ("dan", "cara", "ben", "eve")]
    assert [p["score"] for p in body["people"]] == [0.95, 0.5, 0.0, 0.0]


def test_snowflake_through_the_connector(ranked, monkeypatch):
    event_id, u, _ = ranked
    sf = snowflake_on(monkeypatch, FakeSnowflake(rows=[(uid(u["dan"]), 0.9), (uid(u["ben"]), 0.1)]))
    body = recs(u["ana"], event_id)
    assert people_ids(body)[:2] == [uid(u["dan"]), uid(u["ben"])]
    (_, params), = sf.statements("SELECT")
    assert (params["event_id"], params["viewer"]) == (event_id, uid(u["ana"]))


@pytest.mark.parametrize("fake", [FakeSnowflake(fail=True), FakeSnowflake(delay=1.0)], ids=["error", "timeout"])
def test_snowflake_failure_falls_back_to_pgvector(ranked, monkeypatch, fake):
    event_id, u, _ = ranked
    snowflake_on(monkeypatch, FakeSnowflake(fail=fake.fail, delay=fake.delay), timeout=0.2)
    body = recs(u["ana"], event_id)
    assert people_ids(body) == [uid(u[n]) for n in ("ben", "cara", "dan", "eve")]  # pgvector order


# --- agents rerank -------------------------------------------------------------------------------

def test_agents_rerank(ranked, monkeypatch):
    event_id, u, v = ranked
    group_id = form_group(u["cara"], u["dan"], event_id)
    ana = u["ana"]
    agents = use_agents(monkeypatch, FakeAgents(results=[
        {"candidate_type": "group", "id": group_id, "score": 0.81, "reason": "They need a designer."},
        {"candidate_type": "user", "id": uid(u["eve"]), "score": 0.9, "reason": "  Shared goals.  "},
        {"candidate_type": "user", "id": "usr_not_a_candidate", "score": 0.99, "reason": "Invented"},
        {"candidate_type": "group", "id": uid(u["ben"]), "score": 0.98, "reason": "Wrong type"},
        {"candidate_type": "user", "id": uid(u["eve"]), "score": 0.1, "reason": "Duplicate"},
        {"candidate_type": "user", "id": uid(u["ben"]), "score": "high", "reason": None},
        "garbage",
    ]))
    body = recs(ana, event_id)

    assert body["ranked_by"] == "gemini"
    assert [(p["user_id"], p["score"], p["reason"]) for p in body["people"]] == [
        (uid(u["eve"]), 0.9, "Shared goals."),
        (uid(u["ben"]), round(cos(v["ana"], v["ben"]), 4), None),  # invalid score -> similarity
    ]
    (group,) = body["groups"]
    assert (group["group_id"], group["score"], group["reason"]) == (group_id, 0.81, "They need a designer.")
    assert group["members"] and group["size"] == 2

    (call,) = agents.calls
    assert call["url"] == "http://agents.test/recommend"
    assert call["headers"] == {"X-Internal-Key": "test-internal-key"}
    assert call["timeout"] == get_settings().agents_timeout_s
    sent = call["json"]
    assert sent["event"] == {"event_id": event_id, "type": "structured", "tone": "casual", "description": ""}
    assert sent["viewer"]["user_id"] == uid(ana) and sent["viewer"]["profile_text"].startswith("Event: ")
    assert sent["limit"] == 20  # 10 per type, two types
    assert [(c["candidate_type"], c["id"]) for c in sent["candidates"]] == [
        ("user", uid(u["ben"])), ("user", uid(u["cara"])), ("user", uid(u["dan"])), ("user", uid(u["eve"])),
        ("group", group_id),
    ]
    assert all(set(c) == {"candidate_type", "id", "profile_text", "similarity"} for c in sent["candidates"])
    assert sent["candidates"][0]["similarity"] == round(cos(v["ana"], v["ben"]), 4)
    assert "Member Cara:" in sent["candidates"][-1]["profile_text"]


def test_agents_never_see_other_peoples_handles(login_as, monkeypatch):
    host = login_as("host@x.com", "Host")
    event_id = make_event(host, type="informal")
    ana, ben = login_as("ana@x.com", "Ana"), login_as("ben@x.com", "Ben")
    socials = {"socials": [{"kind": "instagram", "value": "@ana_private"}]}
    assert ana.post(f"/api/events/{event_id}/join", json=socials).status_code == 201
    assert ben.post(f"/api/events/{event_id}/join", json={"socials": [{"kind": "github", "value": "ben-gh"}]}).status_code == 201
    agents = use_agents(monkeypatch, FakeAgents(results=[]))
    recs(ben, event_id)
    (candidate,) = agents.calls[0]["json"]["candidates"]
    assert "@ana_private" not in candidate["profile_text"] and "Socials" not in candidate["profile_text"]
    assert "Event: " in candidate["profile_text"]


@pytest.mark.parametrize(
    "fake",
    [
        FakeAgents(status=500, results=[]),
        FakeAgents(exc=httpx.ReadTimeout("slow")),
        FakeAgents(body=b"not json"),
        FakeAgents(body=b'{"results": "nope"}'),
        FakeAgents(results=[]),
        FakeAgents(results=[{"candidate_type": "user", "id": "usr_invented", "score": 1, "reason": "x"}]),
    ],
    ids=["http_500", "timeout", "not_json", "bad_shape", "empty", "only_unknown_ids"],
)
def test_agents_failure_falls_back_to_similarity(ranked, monkeypatch, fake):
    event_id, u, _ = ranked
    use_agents(monkeypatch, fake)
    body = recs(u["ana"], event_id)
    assert body["ranked_by"] == "similarity"
    assert people_ids(body) == [uid(u[n]) for n in ("ben", "cara", "dan", "eve")]
    assert all(p["reason"] is None for p in body["people"])
    assert len(fake.calls) == 1


def test_agents_skipped_without_internal_key(ranked, monkeypatch):
    event_id, u, _ = ranked
    monkeypatch.setattr(get_settings(), "internal_api_key", "REPLACE_ME")
    agents = use_agents(monkeypatch, FakeAgents(results=[]))
    assert recs(u["ana"], event_id)["ranked_by"] == "similarity"
    assert agents.calls == []


def test_gemini_ranking_caps_each_type_at_limit(ranked, monkeypatch):
    event_id, u, _ = ranked
    use_agents(monkeypatch, FakeAgents(results=lambda req: [
        {"candidate_type": c["candidate_type"], "id": c["id"], "score": 0.5, "reason": "ok"}
        for c in reversed(req["candidates"])
    ]))
    body = recs(u["ana"], event_id, limit=2)
    assert body["ranked_by"] == "gemini"
    assert people_ids(body) == [uid(u["eve"]), uid(u["dan"])]


def test_embedding_rows_untouched_by_recommendations(ranked):
    """Reading recommendations never writes embeddings when Gemini is off."""
    event_id, u, v = ranked
    recs(u["ana"], event_id)
    with Session(dbmod.get_engine()) as db:
        rows = db.exec(select(EventMember.user_id, EventMember.embedded_at)
                       .where(EventMember.event_id == event_id)).all()
    assert all(embedded_at is None for _, embedded_at in rows)
