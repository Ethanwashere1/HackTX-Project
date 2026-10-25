"""Contract section 3: POST /api/events, GET /api/events/{id}, join, and the interview token."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.auth.sessions import hash_token
from app.models import EventMember, InterviewToken, Org, OrgMember, Profile
from app.models.base import utcnow
from tests.test_health_errors import assert_error


def structured(**overrides) -> dict:
    body = {
        "name": "HackTX team-up", "description": "Find your hackathon team",
        "type": "structured", "tone": "casual",
        "group_count": 6, "min_size": 3, "max_size": 4,
        "required_fields": ["skills", "experience_level"],
        "questions": [
            {"text": "What role do you want?", "kind": "single_choice",
             "options": ["frontend", "backend", "design", "ml"], "required": True},
            {"text": "What do you want to build?", "kind": "text", "required": False},
        ],
        "interview_enabled": True, "starts_at": "2026-10-25T15:00:00Z",
    }
    body.update(overrides)
    return body


def informal(**overrides) -> dict:
    body = {"name": "Study buddies", "type": "informal", "tone": "professional"}
    body.update(overrides)
    return body


def create(client, body) -> str:
    resp = client.post("/api/events", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["event_id"]


def make_org(db, members: dict[str, str]) -> str:
    """An org whose members are {user_id: status}."""
    org = Org(name="UT Austin")
    db.add(org)
    db.flush()
    for user_id, status in members.items():
        db.add(OrgMember(org_id=org.id, user_id=user_id, status=status))
    db.commit()
    return org.id


def good_join(client, event_id):
    q = client.get(f"/api/events/{event_id}").json()["questions"]
    return {
        "answers": [{"question_id": q[0]["question_id"], "value": "frontend"},
                    {"question_id": q[1]["question_id"], "value": "climate apps"}],
        "fields": {"skills": ["react", "figma"], "experience_level": "intermediate"},
        "socials": [{"kind": "github", "value": "ana-ruiz"}, {"kind": "instagram", "value": "@ana"}],
    }


# --- auth ----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [("post", "/api/events"), ("get", "/api/events/evt_x"), ("post", "/api/events/evt_x/join"),
     ("post", "/api/events/evt_x/interview")],
)
def test_events_require_login(client, method, path):
    kwargs = {"json": {}} if method == "post" else {}
    assert_error(getattr(client, method)(path, **kwargs), 401, "unauthenticated")


def test_unknown_event_is_404(login_as):
    c = login_as()
    assert_error(c.get("/api/events/evt_nope"), 404, "not_found")
    assert_error(c.post("/api/events/evt_nope/join", json={}), 404, "not_found")
    assert_error(c.post("/api/events/evt_nope/interview"), 404, "not_found")


# --- create + get --------------------------------------------------------------------------------

def test_create_structured_event_and_get_it(login_as):
    host = login_as("host@utexas.edu", "Hannah Host")
    resp = host.post("/api/events", json=structured())
    assert resp.status_code == 201, resp.text
    event_id = resp.json()["event_id"]
    assert event_id.startswith("evt_")
    assert resp.json() == {"event_id": event_id,
                           "share_url": f"http://localhost:5173/events/{event_id}"}

    body = host.get(f"/api/events/{event_id}").json()
    questions = body.pop("questions")
    assert body == {
        "event_id": event_id, "org_id": None, "name": "HackTX team-up",
        "description": "Find your hackathon team", "type": "structured", "tone": "casual",
        "group_count": 6, "min_size": 3, "max_size": 4, "max_groups_per_user": 1,
        "required_fields": ["skills", "experience_level"], "interview_enabled": True,
        "starts_at": "2026-10-25T15:00:00Z", "created_at": body["created_at"],
        "share_url": f"http://localhost:5173/events/{event_id}",
        "host": {"user_id": host.user["user_id"], "name": "Hannah Host"},
        "my_membership": None, "stats": {"member_count": 0, "groups_formed": 0},
    }
    assert body["created_at"].endswith("Z")
    assert [q["question_id"][:2] for q in questions] == ["q_", "q_"]
    assert [(q["text"], q["kind"], q["options"], q["required"]) for q in questions] == [
        ("What role do you want?", "single_choice", ["frontend", "backend", "design", "ml"], True),
        ("What do you want to build?", "text", None, False),
    ]


def test_host_can_raise_max_groups_per_user(login_as):
    c = login_as()
    event_id = create(c, structured(max_groups_per_user=3))
    assert c.get(f"/api/events/{event_id}").json()["max_groups_per_user"] == 3


def test_create_informal_event(login_as):
    c = login_as()
    event_id = create(c, informal())
    body = c.get(f"/api/events/{event_id}").json()
    assert (body["group_count"], body["min_size"], body["max_size"], body["max_groups_per_user"]) == (
        None, None, None, None)
    assert body["questions"] == [] and body["required_fields"] == []
    assert body["interview_enabled"] is False and body["starts_at"] is None


@pytest.mark.parametrize(
    "body",
    [
        structured(max_size=None),
        structured(group_count=None),
        structured(min_size=5, max_size=4),
        structured(min_size=0),
        structured(group_count=-1),
        structured(max_groups_per_user=0),
        informal(group_count=3),
        informal(max_groups_per_user=1),
        structured(type="hybrid"),
        structured(tone="formal"),
        structured(name="   "),
        structured(required_fields=["skills", "skills"]),
        structured(required_fields=["Not A Key"]),
        structured(questions=[{"text": "Role?", "kind": "single_choice", "required": True}]),
        structured(questions=[{"text": "Role?", "kind": "multi_choice", "options": ["a", "a"]}]),
        structured(questions=[{"text": "Bio", "kind": "text", "options": ["x"]}]),
        structured(questions=[{"text": "Bio", "kind": "essay"}]),
        structured(questions=[{"text": "", "kind": "text"}]),
    ],
)
def test_create_event_validation(login_as, body):
    assert_error(login_as().post("/api/events", json=body), 422, "validation_error")


# --- org gating ----------------------------------------------------------------------------------

def test_org_event_requires_approved_membership(login_as, db):
    member = login_as("ana@utexas.edu", "Ana")
    pending = login_as("pat@utexas.edu", "Pat")
    outsider = login_as("out@gmail.com", "Out")
    org_id = make_org(db, {member.user["user_id"]: "approved", pending.user["user_id"]: "pending"})

    for c in (pending, outsider):
        assert_error(c.post("/api/events", json=structured(org_id=org_id)), 403, "not_org_member")
    assert_error(member.post("/api/events", json=structured(org_id="org_missing")),
                 403, "not_org_member")

    event_id = create(member, structured(org_id=org_id))
    assert member.get(f"/api/events/{event_id}").json()["org_id"] == org_id
    for c in (pending, outsider):
        assert_error(c.get(f"/api/events/{event_id}"), 403, "not_org_member")
        assert_error(c.post(f"/api/events/{event_id}/join", json={}), 403, "not_org_member")
        assert_error(c.post(f"/api/events/{event_id}/interview"), 403, "not_org_member")


def test_unlisted_event_is_reachable_by_link(login_as):
    host = login_as("host@x.com", "Host")
    event_id = create(host, informal())
    guest = login_as("guest@y.com", "Guest")
    assert guest.get(f"/api/events/{event_id}").status_code == 200
    assert guest.post(f"/api/events/{event_id}/join", json={}).status_code == 201


# --- join ----------------------------------------------------------------------------------------

def test_join_stores_answers_and_builds_profile(login_as, db):
    host = login_as("host@x.com", "Host")
    event_id = create(host, structured())
    ana = login_as("ana@utexas.edu", "Ana")
    body = good_join(ana, event_id)
    resp = ana.post(f"/api/events/{event_id}/join", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"event_id": event_id, "profile_status": "ready",
                           "interview": {"available": True}}

    q1, q2 = (a["question_id"] for a in body["answers"])
    member = db.exec(select(EventMember).where(EventMember.event_id == event_id)).one()
    assert member.user_id == ana.user["user_id"]
    assert member.answers == {q1: "frontend", q2: "climate apps"}
    assert member.fields == {"skills": ["react", "figma"], "experience_level": "intermediate"}
    assert member.embedding is None and member.embedded_at is None
    for snippet in ("HackTX team-up", "react, figma", "intermediate", "What role do you want?",
                    "frontend", "climate apps", "github ana-ruiz"):
        assert snippet in member.profile_text

    profile = db.exec(select(Profile)).one()
    assert profile.user_id == ana.user["user_id"]
    assert profile.socials == [{"kind": "github", "value": "ana-ruiz"},
                               {"kind": "instagram", "value": "@ana"}]

    got = ana.get(f"/api/events/{event_id}").json()
    assert got["my_membership"]["group_id"] is None
    assert got["my_membership"]["joined_at"].endswith("Z")
    assert got["stats"] == {"member_count": 1, "groups_formed": 0}
    assert host.get(f"/api/events/{event_id}").json()["my_membership"] is None


def test_join_twice_is_409(login_as):
    c = login_as()
    event_id = create(c, informal())
    assert c.post(f"/api/events/{event_id}/join", json={}).status_code == 201
    assert_error(c.post(f"/api/events/{event_id}/join", json={}), 409, "already_joined")


def test_optional_answers_may_be_omitted(login_as):
    c = login_as()
    event_id = create(c, structured())
    body = good_join(c, event_id)
    body["answers"] = body["answers"][:1]
    assert c.post(f"/api/events/{event_id}/join", json=body).status_code == 201


def test_answer_kinds(login_as, db):
    c = login_as()
    event_id = create(c, structured(required_fields=[], questions=[
        {"text": "Langs", "kind": "multi_choice", "options": ["py", "ts", "go"], "required": True},
        {"text": "Years", "kind": "number", "required": True},
    ]))
    q = [x["question_id"] for x in c.get(f"/api/events/{event_id}").json()["questions"]]
    resp = c.post(f"/api/events/{event_id}/join", json={"answers": [
        {"question_id": q[0], "value": ["py", "ts", "py"]}, {"question_id": q[1], "value": 2.5}]})
    assert resp.status_code == 201, resp.text
    member = db.exec(select(EventMember)).one()
    assert member.answers == {q[0]: ["py", "ts"], q[1]: 2.5}


def _mutations():
    def missing_required_answer(b):
        b["answers"] = b["answers"][1:]

    def blank_required_answer(b):
        b["answers"][0]["value"] = None

    def bad_option(b):
        b["answers"][0]["value"] = "astronaut"

    def unknown_question(b):
        b["answers"].append({"question_id": "q_unknown", "value": "x"})

    def duplicate_answer(b):
        b["answers"].append(dict(b["answers"][0]))

    def wrong_type(b):
        b["answers"][1]["value"] = 42

    def missing_field(b):
        del b["fields"]["experience_level"]

    def empty_field(b):
        b["fields"]["skills"] = []

    def unknown_field(b):
        b["fields"]["favourite_color"] = "blue"

    def bad_field_type(b):
        b["fields"]["skills"] = {"nested": True}

    return [missing_required_answer, blank_required_answer, bad_option, unknown_question,
            duplicate_answer, wrong_type, missing_field, empty_field, unknown_field, bad_field_type]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_join_rejects_invalid_answers(login_as, db, mutate):
    c = login_as()
    event_id = create(c, structured())
    body = good_join(c, event_id)
    mutate(body)
    assert_error(c.post(f"/api/events/{event_id}/join", json=body), 422, "invalid_answers")
    assert db.exec(select(EventMember)).all() == []
    assert db.exec(select(Profile)).all() == []


def test_join_rejects_unknown_social_kind(login_as):
    c = login_as()
    event_id = create(c, informal())
    resp = c.post(f"/api/events/{event_id}/join", json={"socials": [{"kind": "myspace", "value": "x"}]})
    assert_error(resp, 422, "validation_error")


def test_answers_to_another_events_questions_are_rejected(login_as):
    c = login_as()
    a = create(c, structured())
    b = create(c, structured())
    body = good_join(c, a)
    assert_error(c.post(f"/api/events/{b}/join", json=body), 422, "invalid_answers")


# --- interview -----------------------------------------------------------------------------------

def test_interview_token(login_as, db):
    c = login_as()
    event_id = create(c, structured())
    assert_error(c.post(f"/api/events/{event_id}/interview"), 403, "forbidden")
    c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id))

    resp = c.post(f"/api/events/{event_id}/interview")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["ws_url"] == "ws://agents.test/ws/interview"
    assert body["expires_in"] == 600
    token = body["interview_token"]
    assert token.startswith("itk_") and len(token) > 30

    row = db.exec(select(InterviewToken)).one()
    assert row.token_hash == hash_token(token) and token not in row.token_hash
    assert (row.user_id, row.event_id, row.used_at) == (c.user["user_id"], event_id, None)
    assert timedelta(seconds=590) < row.expires_at - utcnow() <= timedelta(seconds=600)

    # Each call issues a fresh token.
    assert c.post(f"/api/events/{event_id}/interview").json()["interview_token"] != token


def test_interview_disabled_is_409(login_as):
    c = login_as()
    event_id = create(c, informal())
    c.post(f"/api/events/{event_id}/join", json={})
    assert_error(c.post(f"/api/events/{event_id}/interview"), 409, "interview_disabled")
