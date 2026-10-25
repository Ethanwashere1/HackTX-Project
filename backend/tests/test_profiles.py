"""One profile per person, per-event match text, the background hooks and the shared settings."""

import pytest
from sqlmodel import select

from app.config import get_settings
from app.models import EventMember, Profile
from app.services import profiles as profile_svc
from tests.test_events import create, good_join, informal, structured
from tests.test_review_fixes import make_settings


@pytest.fixture
def hooks(monkeypatch):
    """Records the background hook calls instead of running them."""
    calls = {"text_changed": [], "social_lookup": [], "overview": []}
    monkeypatch.setattr(profile_svc, "on_member_text_changed",
                        lambda ids: calls["text_changed"].append(sorted(ids)))
    monkeypatch.setattr(profile_svc, "schedule_social_lookup",
                        lambda uid, socials: calls["social_lookup"].append((uid, socials)))
    monkeypatch.setattr(profile_svc, "schedule_overview_refresh",
                        lambda uid, event_id=None: calls["overview"].append((uid, event_id)))
    return calls


def member(db, event_id: str, user_id: str) -> EventMember:
    db.expire_all()
    return db.exec(select(EventMember).where(EventMember.event_id == event_id,
                                             EventMember.user_id == user_id)).one()


def test_profile_is_shared_across_events_and_socials_merge(login_as, db, hooks):
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, structured()), create(host, informal())
    ana = login_as()
    uid = ana.user["user_id"]

    assert ana.post(f"/api/events/{e1}/join", json=good_join(ana, e1)).status_code == 201
    m1 = member(db, e1, uid)
    assert hooks["text_changed"] == [[m1.id]]
    assert hooks["social_lookup"] == [(uid, [{"kind": "github", "value": "ana-ruiz"},
                                             {"kind": "instagram", "value": "@ana"}])]
    assert hooks["overview"] == [(uid, e1)]

    # The second join replaces the github handle, keeps instagram, and adds discord.
    socials = [{"kind": "github", "value": "ana-new"}, {"kind": "discord", "value": "ana#1"}]
    resp = ana.post(f"/api/events/{e2}/join", json={"socials": socials})
    assert resp.status_code == 201
    assert resp.json() == {"event_id": e2, "profile_status": "ready", "interview": {"available": False}}

    profile = db.exec(select(Profile)).one()  # still a single profile
    assert profile.socials == [{"kind": "instagram", "value": "@ana"},
                               {"kind": "github", "value": "ana-new"},
                               {"kind": "discord", "value": "ana#1"}]
    m1, m2 = member(db, e1, uid), member(db, e2, uid)
    # Both events' texts were rebuilt with the new socials, and both were handed to the hook.
    for m in (m1, m2):
        assert "github ana-new" in m.profile_text and "ana-ruiz" not in m.profile_text
    assert "react, figma" in m1.profile_text and "Study buddies" in m2.profile_text
    assert hooks["text_changed"][1] == sorted([m1.id, m2.id])
    assert hooks["social_lookup"][1] == (uid, socials)
    assert hooks["overview"][1] == (uid, e2)


def test_join_without_new_socials_only_touches_that_event(login_as, db, hooks):
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, informal()), create(host, informal(name="Second"))
    ana = login_as()
    ana.post(f"/api/events/{e1}/join", json={})
    ana.post(f"/api/events/{e2}/join", json={})
    uid = ana.user["user_id"]
    assert hooks["text_changed"] == [[member(db, e1, uid).id], [member(db, e2, uid).id]]
    assert hooks["social_lookup"] == []
    assert hooks["overview"] == [(uid, e1), (uid, e2)]
    assert db.exec(select(Profile)).one().socials == []


def test_failing_hooks_never_fail_the_join(login_as, db, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(profile_svc, "on_member_text_changed", boom)
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", boom)
    monkeypatch.setattr(profile_svc, "schedule_overview_refresh", boom)
    c = login_as()
    event_id = create(c, structured())
    assert c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id)).status_code == 201
    assert db.exec(select(EventMember)).one().profile_text


def test_refresh_member_texts(login_as, db, hooks):
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, informal()), create(host, informal(name="Second"))
    ana = login_as()
    uid = ana.user["user_id"]
    ana.post(f"/api/events/{e1}/join", json={})
    ana.post(f"/api/events/{e2}/join", json={})
    hooks["text_changed"].clear()

    profile = profile_svc.get_or_create_profile(db, uid)
    profile.summary = "Frontend dev who loves climate apps"
    db.add(profile)
    db.commit()

    m1 = member(db, e1, uid)
    assert profile_svc.refresh_member_texts(db, uid, [e1]) == [m1.id]
    assert "Interview summary: Frontend dev" in member(db, e1, uid).profile_text
    assert "Interview summary" not in member(db, e2, uid).profile_text
    assert hooks["text_changed"] == [[m1.id]]

    ids = profile_svc.refresh_member_texts(db, uid)
    assert sorted(ids) == sorted([m1.id, member(db, e2, uid).id])
    assert "Interview summary: Frontend dev" in member(db, e2, uid).profile_text
    assert profile_svc.refresh_member_texts(db, uid, []) == []
    assert len(hooks["text_changed"]) == 2  # no call for an empty refresh


def test_get_or_create_profile_is_idempotent(login_as, db):
    uid = login_as().user["user_id"]
    first = profile_svc.get_or_create_profile(db, uid)
    db.commit()
    again = profile_svc.get_or_create_profile(db, uid, lock=True)
    db.commit()
    assert first.id == again.id and first.id.startswith("prf_")
    assert (again.socials, again.traits, again.transcript, again.summary, again.overview) == (
        [], {}, [], None, None
    )
    assert len(db.exec(select(Profile)).all()) == 1


def test_build_member_text_is_deterministic(login_as, db):
    c = login_as()
    event_id = create(c, structured())
    c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id))
    from app.models import Event
    from app.services.events import event_questions

    event, m = db.get(Event, event_id), db.exec(select(EventMember)).one()
    profile = db.exec(select(Profile)).one()
    text = profile_svc.build_member_text(event, event_questions(db, event_id), m, profile)
    assert text == m.profile_text
    assert text == profile_svc.build_member_text(event, event_questions(db, event_id), m, profile)
    assert "github" not in profile_svc.build_member_text(event, [], m, None)


def test_external_services_are_off_in_tests():
    s = get_settings()
    assert not s.gemini_configured and not s.serpapi_configured and not s.snowflake_configured
    assert s.internal_key_configured and s.internal_api_key == "test-internal-key"
    assert s.agents_url == "http://agents.test"


def test_configured_flags(monkeypatch):
    for key in ("SNOWFLAKE_ROLE", "GEMINI_API_KEY", "SERPAPI_API_KEY", "INTERNAL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    snowflake = {f"snowflake_{k}": "x" for k in
                 ("account", "user", "password", "warehouse", "database", "schema")}
    s = make_settings(monkeypatch, gemini_api_key="g", serpapi_api_key="s",
                      internal_api_key="i", **snowflake)
    assert s.gemini_configured and s.serpapi_configured and s.internal_key_configured
    assert s.snowflake_configured  # the role is optional
    assert (s.gemini_embed_model, s.snowflake_table) == ("gemini-embedding-001", "PROFILE_EMBEDDINGS")
    assert not make_settings(monkeypatch, **{**snowflake, "snowflake_schema": "REPLACE_ME"}).snowflake_configured
    assert not make_settings(monkeypatch, gemini_api_key="REPLACE_ME").gemini_configured
