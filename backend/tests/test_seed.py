"""The demo seed (app.seed): recommendations on seed data, idempotency, the seed-only reset, and the
embedding paths (fake vectors, Gemini, Gemini failing)."""

import math

import httpx
import pytest
from sqlmodel import Session, func, select

from app import db as dbmod
from app import seed
from app.config import EMBEDDING_DIM, get_settings
from app.models import (
    Connection,
    ContactMethod,
    Event,
    EventMember,
    Group,
    GroupMember,
    Message,
    Org,
    OrgMember,
    Profile,
    Request,
    User,
)
from app.services import agents_client, snowflake_store
from tests.test_embeddings import FakeGemini, FakeSnowflake, gemini_on, snowflake_on
from tests.test_recommendations import FakeAgents, group_ids, people_ids, recs
from tests.test_requests import accept_ok, form_group, join, make_event, send_ok, uid

NAMES = {p.key: p.name for p in [seed.HOST, *seed.PEOPLE]}


@pytest.fixture(autouse=True)
def agents_down(monkeypatch):
    """No agents service: recommendations come back in similarity order."""
    monkeypatch.setattr(agents_client, "_post", FakeAgents(exc=httpx.ConnectError("agents down")))
    snowflake_store.reset()
    yield
    snowflake_store.reset()


@pytest.fixture
def seeded() -> seed.SeedResult:
    with Session(dbmod.get_engine()) as db:
        return seed.seed(db, fake_embeddings=True)


def as_seed(login_as, key):
    return login_as(seed.seed_email(key), NAMES[key])


def table_counts() -> dict[str, int]:
    with Session(dbmod.get_engine()) as db:
        return {
            m.__name__: db.exec(select(func.count()).select_from(m)).one()
            for m in (User, Org, OrgMember, Event, EventMember, Group, GroupMember, Request,
                      Connection, Message, ContactMethod, Profile)
        }


# --- what gets seeded ----------------------------------------------------------------------------

def test_seed_creates_org_events_people_groups_and_requests(seeded):
    assert seeded.embedded_with == "fake"
    with Session(dbmod.get_engine()) as db:
        hacktx, study = db.get(Event, seeded.events["hacktx"]), db.get(Event, seeded.events["study"])
        assert (hacktx.type, hacktx.tone, hacktx.group_count, hacktx.max_size) == (
            "structured", "casual", 6, 4)
        assert (study.type, study.tone, study.max_groups_per_user) == ("informal", "professional", None)
        assert hacktx.org_id == study.org_id == seeded.org_id
        users = db.exec(select(User).where(User.id.in_(list(seeded.users.values())))).all()
        assert len(users) == 16 and all(u.email.endswith("@seed.squadup.dev") for u in users)
        assert db.exec(select(func.count()).select_from(OrgMember)
                       .where(OrgMember.org_id == seeded.org_id, OrgMember.status == "approved")).one() == 16

        members = db.exec(select(EventMember).where(EventMember.id.in_(seeded.member_ids))).all()
        assert len(members) == 15 + sum(p.study is not None for p in seed.PEOPLE)
        for m in members:
            # Built the normal way: event header, fields, answers and the person profile.
            assert m.profile_text.startswith("Event: ") and "Interview summary: " in m.profile_text
            assert len(m.embedding) == EMBEDDING_DIM and m.embedded_at is not None
            assert math.isclose(math.sqrt(sum(float(v) ** 2 for v in m.embedding)), 1.0, rel_tol=1e-5)

        sizes = {g.name: len(db.exec(select(GroupMember).where(GroupMember.group_id == g.id)).all())
                 for g in db.exec(select(Group).where(Group.event_id == hacktx.id)).all()}
        assert sizes == {"Team Pixel": 3, "Team Neural": 2, "Team Volt": 4}
        statuses = sorted(db.exec(select(Request.status).where(Request.target_type == "user",
                                                               Request.event_id == study.id)).all())
        assert statuses == ["accepted", "declined", "pending"]
        assert db.exec(select(func.count()).select_from(Connection)).one() == 1
        pixel = db.get(Group, seeded.groups["Team Pixel"])
        assert len(db.exec(select(Message).where(Message.thread_id == pixel.thread_id)).all()) == 3


# --- recommendations on seed data ----------------------------------------------------------------

def test_structured_recommendations_for_a_solo_seed_user(seeded, login_as):
    priya = as_seed(login_as, "priya")
    body = recs(priya, seeded.events["hacktx"])
    u, g = seeded.users, seeded.groups
    assert body["ranked_by"] == "similarity"
    people = people_ids(body)
    assert len(people) == 10 and uid(priya) not in people  # limit 10 of the 14 others
    scores = [p["score"] for p in body["people"]]
    assert scores == sorted(scores, reverse=True) and scores[0] > 0
    # The other ML people rank first, and the ML team leads the open groups; the full team is out.
    assert set(people[:2]) == {u["dev"], u["eli"]}
    assert group_ids(body) == [g["Team Neural"], g["Team Pixel"]]


def test_structured_exclusions_on_seed_data(seeded, login_as):
    event_id, u, g = seeded.events["hacktx"], seeded.users, seeded.groups
    # Jordan has a pending request to Team Pixel: that group is excluded.
    assert group_ids(recs(as_seed(login_as, "jordan"), event_id)) == [g["Team Neural"]]
    # Ana is in Team Pixel: no group-mates, and no groups (max_groups_per_user is 1).
    body = recs(as_seed(login_as, "ana"), event_id, limit=50)
    assert body["groups"] == []
    assert not {u["ana"], u["ben"], u["cara"]} & set(people_ids(body))
    # Mia -> Noah is pending; Kai and Liam declined each other.
    assert u["noah"] not in people_ids(recs(as_seed(login_as, "mia"), event_id, limit=50))
    assert u["mia"] not in people_ids(recs(as_seed(login_as, "noah"), event_id, limit=50))
    assert u["liam"] not in people_ids(recs(as_seed(login_as, "kai"), event_id, limit=50))
    assert u["kai"] not in people_ids(recs(as_seed(login_as, "liam"), event_id, limit=50))


def test_informal_recommendations_on_seed_data(seeded, login_as):
    event_id, u = seeded.events["study"], seeded.users
    body = recs(as_seed(login_as, "ben"), event_id, limit=50)
    assert body["groups"] == [] and body["people"]
    assert u["hiro"] not in people_ids(body)  # connected
    assert u["ana"] not in people_ids(recs(as_seed(login_as, "jordan"), event_id, limit=50))  # pending
    assert u["noah"] not in people_ids(recs(as_seed(login_as, "mia"), event_id, limit=50))  # declined


# --- idempotency and reset -----------------------------------------------------------------------

def test_running_twice_creates_nothing_new(seeded):
    before = table_counts()
    with Session(dbmod.get_engine()) as db:
        again = seed.seed(db, fake_embeddings=True)
    assert table_counts() == before
    assert (again.org_id, again.events, again.users, again.groups) == (
        seeded.org_id, seeded.events, seeded.users, seeded.groups)


def test_reset_with_no_real_users_removes_all_seed_data(seeded, db):
    assert seed.wipe(db) == {"users": 16, "users_kept": 0, "orgs": 1, "orgs_kept": 0, "events": 2}
    assert table_counts() == dict.fromkeys(table_counts(), 0)
    assert seed.wipe(db) == {"users": 0, "users_kept": 0, "orgs": 0, "orgs_kept": 0, "events": 0}


def test_reset_keeps_real_users_seed_org_membership_and_events(seeded, login_as, db, capsys):
    # A real attendee: their utexas.edu email auto-approves them into the seed org (the point of
    # the demo). They host an event in it and also join the seed HackTX event.
    real = login_as("real@utexas.edu", "Real Person")
    assert real.post(f"/api/orgs/{seeded.org_id}/join").json() == {"status": "approved"}
    own_event = make_event(real, org_id=seeded.org_id)
    join(real, own_event)
    q = real.get(f"/api/events/{seeded.events['hacktx']}").json()["questions"]
    resp = real.post(f"/api/events/{seeded.events['hacktx']}/join", json={
        "answers": [{"question_id": q[0]["question_id"], "value": "Frontend"},
                    {"question_id": q[1]["question_id"], "value": "A campus app"}],
        "fields": {"skills": ["React"], "experience_level": "beginner"},
    })
    assert resp.status_code == 201, resp.text
    contacts = {"contacts": [{"kind": "discord", "value": "real#1"}]}
    assert real.put("/api/me/contacts", json=contacts).status_code == 200

    # Someone who signed in with Google on the seed domain is a real user, not seed data.
    google_user = User(email="lookalike@seed.squadup.dev", name="Lookalike", google_sub="g-123")
    db.add(google_user)
    db.commit()

    removed = seed.wipe(db)
    # The org is kept (a real member hosts an event in it), so is its creator (the seed host).
    assert removed == {"users": 15, "users_kept": 1, "orgs": 0, "orgs_kept": 1, "events": 2}
    db.expire_all()
    assert db.get(User, google_user.id) is not None
    assert seed.seed_user_ids(db) == [seeded.users["morgan"]]
    org = db.get(Org, seeded.org_id)
    assert org is not None and org.email_domains == ["utexas.edu"]
    # Only the real user's membership is left in it; the seed users' memberships are gone.
    assert db.exec(select(OrgMember.user_id, OrgMember.status, OrgMember.role)
                   .where(OrgMember.org_id == org.id)).all() == [(uid(real), "approved", "member")]
    # The seed events are gone (with the real user's membership in HackTX); theirs survives.
    assert db.exec(select(Event.id, Event.org_id)).all() == [(own_event, org.id)]
    user = db.get(User, uid(real))
    assert user is not None and user.email == "real@utexas.edu"
    assert db.exec(select(EventMember.event_id).where(EventMember.user_id == user.id)).all() == [own_event]
    assert db.exec(select(Profile).where(Profile.user_id == user.id)).first() is not None
    assert db.exec(select(ContactMethod.value).where(ContactMethod.user_id == user.id)).all() == ["real#1"]
    assert real.get(f"/api/events/{own_event}").status_code == 200  # still signed in
    feed = real.get(f"/api/orgs/{org.id}/feed").json()["events"]
    assert [e["event_id"] for e in feed] == [own_event]

    # Seeding again finds the kept org (through its kept creator) instead of making a second one.
    with Session(dbmod.get_engine()) as s:
        again = seed.seed(s, fake_embeddings=True)
    assert again.org_id == org.id and again.users["morgan"] == seeded.users["morgan"]
    assert db.exec(select(func.count()).select_from(Org)).one() == 1
    approved = db.exec(select(func.count()).select_from(OrgMember)
                       .where(OrgMember.org_id == org.id, OrgMember.status == "approved")).one()
    assert approved == 17
    feed = real.get(f"/api/orgs/{org.id}/feed").json()["events"]
    assert {e["event_id"] for e in feed} == {own_event, *again.events.values()}

    # The CLI says what it kept.
    assert seed.main(["--wipe"]) == 0
    out = capsys.readouterr().out
    assert "Removed seed data: 15 user(s), 0 org(s), 2 event(s)" in out
    assert "Kept (still used by real users): 1 seed user(s), 1 seed org(s)" in out
    assert db.exec(select(Event.id)).all() == [own_event]


def test_reset_keeps_seed_users_that_real_users_team_up_or_chat_with(seeded, login_as, db):
    # A real host's own (unlisted) events, where seed users take part via dev login.
    host = login_as("host@gmail.com", "Hannah Host")
    ana, ben, cara = (as_seed(login_as, k) for k in ("ana", "ben", "cara"))
    team_event = make_event(host)
    for c in (host, ana, cara):
        join(c, team_event)
    group_id = form_group(host, ana, team_event)  # grouped with a seed user
    thread_id = db.get(Group, group_id).thread_id
    for c, text in ((host, "hi Ana"), (ana, "hi Hannah")):  # and chatting
        assert c.post(f"/api/threads/{thread_id}/messages", json={"text": text}).status_code == 201
    pending = send_ok(cara, team_event, uid(host))["request_id"]
    study_event = make_event(host, type="informal")
    join(host, study_event)
    join(ben, study_event)
    connection_id = accept_ok(host, send_ok(ben, study_event, uid(host))["request_id"])["connection_id"]

    removed = seed.wipe(db)
    # Ana, Ben and Cara are kept: deleting them would cascade into the real host's group, chat,
    # connection and request. Nobody real uses the seed org, so it goes with the other 13 users.
    assert removed == {"users": 13, "users_kept": 3, "orgs": 1, "orgs_kept": 0, "events": 2}
    db.expire_all()
    u = seeded.users
    assert sorted(seed.seed_user_ids(db)) == sorted([u["ana"], u["ben"], u["cara"]])
    assert db.get(Org, seeded.org_id) is None
    assert set(db.exec(select(Event.id)).all()) == {team_event, study_event}
    assert set(db.exec(select(GroupMember.user_id).where(GroupMember.group_id == group_id)).all()) == {
        uid(host), u["ana"]}
    assert [m["text"] for m in host.get(f"/api/threads/{thread_id}/messages").json()["messages"]] == [
        "hi Ana", "hi Hannah"]
    assert db.get(Connection, connection_id) is not None
    assert db.get(Request, pending).status == "pending"
    # Their seed-event data is gone: Ana is only in the real host's event now.
    assert db.exec(select(EventMember.event_id).where(EventMember.user_id == u["ana"])).all() == [
        team_event]
    assert host.get(f"/api/groups/{group_id}").status_code == 200

    # Seeding again reuses the kept seed users, and the next reset keeps them again.
    with Session(dbmod.get_engine()) as s:
        again = seed.seed(s, fake_embeddings=True)
    assert len(again.users) == 16 and again.users["ana"] == u["ana"]
    assert seed.wipe(db) == removed


def test_reset_removes_seed_vectors_from_snowflake(seeded, monkeypatch, db):
    sf = snowflake_on(monkeypatch, FakeSnowflake())
    seed.wipe(db)
    deleted = {params["event_id"] for sql, params in sf.executed if sql.startswith("DELETE")}
    assert deleted == set(seeded.events.values())


# --- CLI -----------------------------------------------------------------------------------------

def test_cli_seed_reset_and_wipe(capsys):
    assert seed.main(["--fake-embeddings"]) == 0
    out = capsys.readouterr().out
    assert "embeddings: fake" in out
    assert '{"email": "priya@seed.squadup.dev", "name": "Priya Sharma"}' in out
    first = table_counts()

    assert seed.main(["--reset", "--fake-embeddings"]) == 0
    assert "Removed seed data: 16 user(s), 1 org(s), 2 event(s)" in capsys.readouterr().out
    assert table_counts() == first

    assert seed.main(["--wipe"]) == 0
    assert table_counts()["User"] == 0


def test_cli_refuses_reset_and_wipe_outside_local_without_yes(monkeypatch, capsys):
    assert seed.main(["--fake-embeddings"]) == 0
    capsys.readouterr()
    before = table_counts()
    monkeypatch.setattr(get_settings(), "app_env", "production")
    for flag in ("--wipe", "--reset"):
        assert seed.main([flag, "--fake-embeddings"]) == 2
        err = capsys.readouterr().err
        assert f"Refusing {flag}: APP_ENV is 'production'" in err and "--yes" in err
    assert table_counts() == before
    assert seed.main(["--wipe", "--yes"]) == 0
    assert table_counts()["User"] == 0


# --- embeddings ----------------------------------------------------------------------------------

def test_fake_embedding_is_deterministic_unit_length_and_meaningful():
    ml = "Event: X (structured, casual)\nSkills: Python, PyTorch, LLMs\nA: ML / AI"
    ml2 = "Event: X (structured, casual)\nSkills: Python, NLP, LLMs\nA: ML / AI"
    art = "Event: X (structured, casual)\nSkills: Figma, Illustration\nA: Design"
    v = seed.fake_embedding(ml)
    assert v == seed.fake_embedding(ml) and len(v) == EMBEDDING_DIM
    assert math.isclose(sum(x * x for x in v), 1.0)

    def cos(a, b):
        return sum(x * y for x, y in zip(seed.fake_embedding(a), seed.fake_embedding(b)))

    assert cos(ml, ml2) > cos(ml, art)
    assert seed.fake_embedding("Event: X (informal, casual)\nQ: Who?") is None  # nothing of their own


def test_uses_gemini_when_configured(monkeypatch):
    gemini = gemini_on(monkeypatch, FakeGemini())
    with Session(dbmod.get_engine()) as db:
        result = seed.seed(db)
        assert result.embedded_with == "gemini"
        texts = dict(db.exec(select(EventMember.id, EventMember.profile_text)
                             .where(EventMember.id.in_(result.member_ids))).all())
    assert sorted(gemini.texts) == sorted(texts.values())


def test_falls_back_to_fake_embeddings_when_gemini_fails(monkeypatch, caplog):
    gemini_on(monkeypatch, FakeGemini(lambda url, json: httpx.Response(
        500, json={}, request=httpx.Request("POST", url))))
    with Session(dbmod.get_engine()) as db:
        result = seed.seed(db)
        vectors = db.exec(select(EventMember.embedding).where(EventMember.id.in_(result.member_ids))).all()
    assert result.embedded_with == "fake"
    assert all(v is not None for v in vectors)
    assert "falling back to fake embeddings" in caplog.text
