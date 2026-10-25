"""AI feature wiring (CONTRACT v1.0-pre.5): profile, overview regen, question-suggestions."""

import json

import httpx
from sqlmodel import select

from app.models import Profile
from app.services import agents_client
from app.services import profiles as profile_svc
from tests.test_events import create, good_join, structured
from tests.test_health_errors import assert_error
from tests.test_profiles import member
from tests.test_recommendations import FakeAgents, recs, setup_event, use_agents
from tests.test_requests import form_group, uid
from tests.test_threads_groups import set_contacts

# Captured before conftest no-ops it; restore in tests that exercise overview regen.
_REAL_SCHEDULE_OVERVIEW = profile_svc.schedule_overview_refresh


def _mock_agents(monkeypatch, handler):
    real = httpx.Client

    def factory(**kwargs):
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(agents_client.httpx, "Client", factory)


def _enable_overview_hook(monkeypatch):
    monkeypatch.setattr(profile_svc, "schedule_overview_refresh", _REAL_SCHEDULE_OVERVIEW)


# --- GET /api/me/profile -------------------------------------------------------------------------

def test_get_me_profile_empty(login_as):
    c = login_as()
    resp = c.get("/api/me/profile")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "user_id": c.user["user_id"],
        "name": "Ana Ruiz",
        "email": "ana@utexas.edu",
        "overview": None,
        "summary": None,
        "traits": None,
        "contacts": [],
        "socials": [],
        "interviewed": False,
    }


def test_get_me_profile_populated(login_as, db):
    c = login_as()
    user_id = c.user["user_id"]
    c.put("/api/me/contacts", json={"contacts": [{"kind": "discord", "value": "ana#1"}]})
    profile = profile_svc.get_or_create_profile(db, user_id)
    profile.overview = "Frontend-leaning builder who wants a climate hack."
    profile.summary = "Loves climate apps; prefers pairing."
    profile.traits = {
        "working_style": "pairing",
        "topics": "climate,react",
        "group_need": "hackathon teammates",
    }
    profile.socials = [{"kind": "github", "value": "ana-ruiz"}]
    db.add(profile)
    db.commit()

    body = c.get("/api/me/profile").json()
    assert body["overview"].startswith("Frontend-leaning")
    assert body["summary"].startswith("Loves climate")
    assert body["traits"]["group_need"] == "hackathon teammates"
    assert body["contacts"] == [{"kind": "discord", "value": "ana#1"}]
    assert body["socials"] == [{"kind": "github", "value": "ana-ruiz"}]


def test_get_me_profile_requires_login(client):
    assert_error(client.get("/api/me/profile"), 401, "unauthenticated")


# --- overview after join -------------------------------------------------------------------------

def test_join_persists_overview_when_agents_ok(login_as, db, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/profile-overview"
        assert request.headers.get("X-Internal-Key") == "test-internal-key"
        body = json.loads(request.content)
        calls.append(body)
        assert body["user"]["name"] == "Ana Ruiz"
        assert body["answers"]
        assert body["fields"]["skills"] == ["react", "figma"]
        assert body["event"]["type"] == "structured"
        assert body["social_notes"] is None  # SerpAPI info never feeds the shared overview
        return httpx.Response(200, json={
            "overview": "Frontend-leaning builder focused on climate apps.",
            "traits": {
                "working_style": "pairing",
                "topics": "climate,react",
                "group_need": "hackathon teammates",
            },
        })

    _mock_agents(monkeypatch, handler)
    _enable_overview_hook(monkeypatch)
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda *a, **k: None)
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", lambda *a, **k: None)

    host = login_as("host@x.com", "Host")
    event_id = create(host, structured())
    c = login_as()
    resp = c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id))
    assert resp.status_code == 201, resp.text

    db.expire_all()
    profile = db.exec(select(Profile).where(Profile.user_id == c.user["user_id"])).one()
    assert profile.overview == "Frontend-leaning builder focused on climate apps."
    assert profile.traits["topics"] == "climate,react"
    assert calls and "Overview:" in member(db, event_id, c.user["user_id"]).profile_text


def test_join_succeeds_when_overview_agents_fails(login_as, db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("agents down", request=request)

    _mock_agents(monkeypatch, handler)
    _enable_overview_hook(monkeypatch)
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda *a, **k: None)
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", lambda *a, **k: None)

    host = login_as("host@x.com", "Host")
    event_id = create(host, structured())
    c = login_as()
    profile = profile_svc.get_or_create_profile(db, c.user["user_id"])
    profile.overview = "Prior overview"
    db.add(profile)
    db.commit()

    resp = c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id))
    assert resp.status_code == 201, resp.text
    db.expire_all()
    assert db.exec(select(Profile).where(Profile.user_id == c.user["user_id"])).one().overview == "Prior overview"


def test_join_succeeds_when_overview_returns_500(login_as, db, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "overview_failed"}})

    _mock_agents(monkeypatch, handler)
    _enable_overview_hook(monkeypatch)
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda *a, **k: None)
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", lambda *a, **k: None)

    host = login_as("host@x.com", "Host")
    event_id = create(host, structured())
    c = login_as()
    assert c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id)).status_code == 201
    assert db.exec(select(Profile).where(Profile.user_id == c.user["user_id"])).one().overview is None


# --- POST /api/question-suggestions --------------------------------------------------------------

def _suggest_body(**overrides):
    body = {
        "name": "HackTX team-up",
        "type": "structured",
        "tone": "casual",
        "description": "Find your hackathon team",
        "existing_questions": [
            {
                "text": "What role do you want?",
                "kind": "single_choice",
                "options": ["frontend", "backend", "design", "ml"],
            },
        ],
        "count": 3,
        "hint": "availability and what they want to build",
    }
    body.update(overrides)
    return body


def test_question_suggestions_proxies_agents(login_as, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/generate-questions"
        assert request.headers.get("X-Internal-Key") == "test-internal-key"
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"questions": [
            {
                "text": "How many hours can you commit?",
                "kind": "single_choice",
                "options": ["under 8", "8–16", "all weekend"],
                "required": True,
            },
            {
                "text": "What do you want to build?",
                "kind": "text",
                "options": None,
                "required": False,
            },
        ]})

    _mock_agents(monkeypatch, handler)
    c = login_as()
    resp = c.post("/api/question-suggestions", json=_suggest_body())
    assert resp.status_code == 200, resp.text
    qs = resp.json()["questions"]
    assert len(qs) == 2
    assert qs[0]["kind"] == "single_choice" and qs[0]["required"] is True
    assert qs[1]["options"] is None
    assert seen["body"]["count"] == 3
    assert seen["body"]["event"]["name"] == "HackTX team-up"
    assert seen["body"]["hint"].startswith("availability")


def test_question_suggestions_agents_timeout_is_502(login_as, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    _mock_agents(monkeypatch, handler)
    c = login_as()
    assert_error(
        c.post("/api/question-suggestions", json=_suggest_body()), 502, "agents_unavailable"
    )


def test_question_suggestions_agents_5xx_is_502(login_as, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": {"code": "quizgen_failed"}})

    _mock_agents(monkeypatch, handler)
    c = login_as()
    assert_error(
        c.post("/api/question-suggestions", json=_suggest_body()), 502, "agents_unavailable"
    )


def test_question_suggestions_validates_count(login_as):
    c = login_as()
    assert_error(
        c.post("/api/question-suggestions", json=_suggest_body(count=0)), 422, "validation_error"
    )
    assert_error(
        c.post("/api/question-suggestions", json=_suggest_body(count=11)), 422, "validation_error"
    )
    assert_error(
        c.post("/api/question-suggestions", json=_suggest_body(type="party")),
        422,
        "validation_error",
    )
    assert_error(
        c.post(
            "/api/question-suggestions",
            json=_suggest_body(existing_questions=[{"text": "x", "kind": "single_choice"}]),
        ),
        422,
        "validation_error",
    )


def test_question_suggestions_requires_login(client):
    assert_error(
        client.post("/api/question-suggestions", json=_suggest_body()), 401, "unauthenticated"
    )


# --- recommend enrichment ------------------------------------------------------------------------
# main tested its recommend.py helpers directly; they are folded into services/recommendations.py,
# so this checks the same payload through GET /recommendations and the agents rerank call.

def _set_profile(db, client, **values):
    profile = db.exec(select(Profile).where(Profile.user_id == uid(client))).one()
    for k, v in values.items():
        setattr(profile, k, v)
    db.add(profile)
    db.commit()


def test_recommend_payload_includes_traits_and_prefers_overview(login_as, db, monkeypatch):
    event_id, u = setup_event(login_as, ["ana", "ben"])
    _set_profile(db, u["ana"], traits={"working_style": "pairing", "topics": "climate, react",
                                       "group_need": "hackathon teammates"})
    _set_profile(db, u["ben"], overview="Overview blurb", summary="Interview only",
                 traits={"topics": "climate,apis", "highlights": ["won a hackathon"]})
    agents = use_agents(monkeypatch, FakeAgents(results=lambda body: [
        {"candidate_type": "user", "id": uid(u["ben"]), "score": 0.9, "reason": "overlap"}]))

    body = recs(u["ana"], event_id)
    sent = agents.calls[0]["json"]
    viewer = sent["viewer"]
    assert viewer["traits"]["working_style"] == "pairing"
    assert viewer["topic_signals"] == ["climate", "react"]
    assert viewer["group_need"] == "hackathon teammates"
    (cand,) = sent["candidates"]
    assert cand["candidate_type"] == "user" and cand["id"] == uid(u["ben"])
    assert cand["topic_signals"] == ["climate", "apis"] and "group_need" not in cand
    assert cand["traits"]["highlights"] == "won a hackathon"  # agents take {str: str}
    assert body["people"][0]["summary"] == "Overview blurb"

    _set_profile(db, u["ben"], overview=None)
    assert recs(u["ana"], event_id)["people"][0]["summary"] == "Interview only"


def test_team_page_prefers_overview_over_summary(login_as, db, monkeypatch):
    monkeypatch.setattr(profile_svc, "schedule_overview_refresh", lambda *a, **k: None)
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda *a, **k: None)
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", lambda *a, **k: None)

    host = login_as("host@x.com", "Host")
    e = create(host, structured(max_size=4, min_size=2, group_count=3))
    ana, ben = login_as("ana@x.com", "Ana"), login_as("ben@x.com", "Ben")
    for c in (ana, ben):
        assert c.post(f"/api/events/{e}/join", json=good_join(c, e)).status_code == 201
    set_contacts(ana, "ana#1")
    profile = db.exec(select(Profile).where(Profile.user_id == uid(ana))).one()
    profile.summary = "Interview summary"
    profile.overview = "AI overview"
    db.add(profile)
    db.commit()
    gid = form_group(ana, ben, e)
    by_id = {m["user_id"]: m for m in ben.get(f"/api/groups/{gid}").json()["members"]}
    assert by_id[uid(ana)]["summary"] == "AI overview"
