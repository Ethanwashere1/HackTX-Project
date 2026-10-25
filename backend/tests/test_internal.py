"""Contract section 8: the internal interview endpoints the agents service calls (X-Internal-Key)."""

import threading
import time
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from app import db as dbmod
from app.auth.sessions import hash_token
from app.config import get_settings
from app.errors import AppError
from app.models import EventMember, InterviewToken, OrgMember, Profile
from app.models.base import utcnow
from app.services import interviews as interview_svc
from app.services import profiles as profile_svc
from tests.test_events import create, good_join, informal, make_org, other_host, structured
from tests.test_health_errors import assert_error

KEY = {"X-Internal-Key": "test-internal-key"}  # conftest sets INTERNAL_API_KEY to this

SUMMARY = {
    "transcript": [
        {"role": "interviewer", "text": "What do you want to build?", "ts": "2026-10-25T15:00:00Z"},
        {"role": "user", "text": "Climate apps, I mostly do React", "ts": "2026-10-25T15:00:05Z"},
    ],
    "summary": "Frontend dev who loves climate apps; wants a chill but ambitious team.",
    "traits": {"working_style": "pairing", "ambition": "win", "highlights": ["React", "Figma"]},
    "input_mode": "voice",
}


@pytest.fixture
def text_changed(monkeypatch):
    """Records on_member_text_changed calls instead of running them."""
    calls: list[list[str]] = []
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda ids: calls.append(sorted(ids)))
    return calls


@pytest.fixture
def interview(login_as):
    """Ana joins a structured event and gets an interview token: (ana, event_id, token)."""
    host = login_as("host@x.com", "Host")
    event_id = create(host, structured())
    ana = login_as()
    assert ana.post(f"/api/events/{event_id}/join", json=good_join(ana, event_id)).status_code == 201
    token = ana.post(f"/api/events/{event_id}/interview").json()["interview_token"]
    return ana, event_id, token


def config(client, token, headers=KEY):
    return client.get(f"/internal/interviews/{token}/config", headers=headers)


def post_summary(client, token, body=SUMMARY, headers=KEY):
    return client.post(f"/internal/interviews/{token}/summary", json=body, headers=headers)


def token_row(db, token) -> InterviewToken | None:
    db.expire_all()
    return db.get(InterviewToken, hash_token(token))


def set_token(db, token, **values) -> None:
    row = token_row(db, token)
    for k, v in values.items():
        setattr(row, k, v)
    db.add(row)
    db.commit()


# --- X-Internal-Key ------------------------------------------------------------------------------

@pytest.mark.parametrize("call", [config, post_summary])
def test_missing_key_is_401(client, call):
    assert_error(call(client, "itk_x", headers={}), 401, "unauthenticated")


@pytest.mark.parametrize("call", [config, post_summary])
# b"\xe9" arrives as a non-ASCII str, which a plain str compare_digest would reject with a 500.
@pytest.mark.parametrize("key", ["wrong", "test-internal-key ", "TEST-INTERNAL-KEY", b"\xe9"])
def test_wrong_key_is_403(client, call, key):
    assert_error(call(client, "itk_x", headers={"X-Internal-Key": key}), 403, "forbidden")


@pytest.mark.parametrize("configured", ["", "REPLACE_ME"])
def test_unconfigured_key_rejects_every_call(client, interview, monkeypatch, configured):
    _, _, token = interview
    monkeypatch.setattr(get_settings(), "internal_api_key", configured)
    for key in ("", "REPLACE_ME", "test-internal-key"):
        resp = config(client, token, headers={"X-Internal-Key": key} if key else {})
        assert_error(resp, 401 if not key else 403, "unauthenticated" if not key else "forbidden")


def test_key_is_checked_before_the_token(client, interview, db):
    _, _, token = interview
    assert_error(config(client, token, headers={"X-Internal-Key": "wrong"}), 403, "forbidden")
    assert token_row(db, token).used_at is None  # a rejected call does not claim the token


# --- tokens --------------------------------------------------------------------------------------

@pytest.mark.parametrize("token", ["itk_unknown", "x" * 500])
def test_unknown_token_is_401(client, token):
    assert_error(config(client, token), 401, "unauthenticated")
    assert_error(post_summary(client, token), 401, "unauthenticated")


def test_expired_token_is_401(client, interview, db):
    _, _, token = interview
    set_token(db, token, expires_at=utcnow() - timedelta(seconds=1))
    assert_error(config(client, token), 401, "unauthenticated")
    assert token_row(db, token).used_at is None


def test_config_token_is_single_use(client, interview):
    _, _, token = interview
    assert config(client, token).status_code == 200
    assert_error(config(client, token), 401, "unauthenticated")


def test_summary_token_is_single_use(client, interview, db, text_changed):
    _, _, token = interview
    config(client, token)
    assert post_summary(client, token).status_code == 200
    resp = post_summary(client, token, {**SUMMARY, "summary": "Overwritten"})
    assert_error(resp, 401, "unauthenticated")
    db.expire_all()
    assert db.exec(select(Profile)).one().summary == SUMMARY["summary"]
    assert len(text_changed) == 1


def test_summary_needs_a_started_interview(client, interview, db):
    _, _, token = interview
    assert_error(post_summary(client, token), 401, "unauthenticated")
    assert token_row(db, token) is not None and db.exec(select(Profile)).one().summary is None


def test_summary_deadline_counts_from_the_claim(client, interview, db, text_changed):
    _, _, token = interview
    config(client, token)
    # The 10-minute issue window has passed, but the interview started in time: still accepted.
    set_token(db, token, expires_at=utcnow() - timedelta(minutes=1),
              used_at=utcnow() - timedelta(minutes=9))
    assert post_summary(client, token).status_code == 200


def test_summary_after_the_window_is_401(client, interview, db):
    _, _, token = interview
    config(client, token)
    set_token(db, token, used_at=utcnow() - interview_svc.SUMMARY_WINDOW - timedelta(seconds=1))
    assert_error(post_summary(client, token), 401, "unauthenticated")


def test_concurrent_config_calls_claim_once(interview, monkeypatch):
    _, _, token = interview
    real_check = interview_svc._require_event_member

    def slow_check(db, row):
        time.sleep(0.3)  # widen the window between reading used_at and claiming the token
        return real_check(db, row)

    monkeypatch.setattr(interview_svc, "_require_event_member", slow_check)
    barrier = threading.Barrier(2)
    results: list[str | None] = [None, None]

    def run(i: int) -> None:
        with Session(dbmod.get_engine()) as s:
            barrier.wait()
            try:
                interview_svc.claim_for_config(s, token)
                results[i] = "ok"
            except AppError as exc:
                results[i] = exc.code

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == ["ok", "unauthenticated"]


def test_member_who_lost_org_access_is_403(client, login_as, db):
    host, ana = other_host(login_as), login_as()
    org_id = make_org(db, {ana.user["user_id"]: "approved", host.user["user_id"]: "approved"})
    event_id = create(host, structured(org_id=org_id))
    ana.post(f"/api/events/{event_id}/join", json=good_join(ana, event_id))
    token = ana.post(f"/api/events/{event_id}/interview").json()["interview_token"]
    om = db.exec(select(OrgMember).where(OrgMember.user_id == ana.user["user_id"])).one()
    om.status = "declined"
    db.add(om)
    db.commit()
    assert_error(config(client, token), 403, "forbidden")
    assert token_row(db, token).used_at is None


# --- happy path ----------------------------------------------------------------------------------

def test_summary_schedules_the_overview_refresh(client, interview, text_changed, monkeypatch):
    ana, event_id, token = interview
    calls = []
    monkeypatch.setattr(profile_svc, "schedule_overview_refresh",
                        lambda uid, event_id=None: calls.append((uid, event_id)))
    assert config(client, token).status_code == 200
    assert post_summary(client, token).status_code == 200
    assert calls == [(ana.user["user_id"], event_id)]


def test_config_returns_the_contract_shape(client, interview, db):
    ana, event_id, token = interview
    uid = ana.user["user_id"]
    profile = db.exec(select(Profile)).one()
    profile.social_notes = "GitHub: 40 repos, mostly React"
    db.add(profile)
    db.commit()
    q1, q2 = (q["question_id"] for q in ana.get(f"/api/events/{event_id}").json()["questions"])

    resp = config(client, token)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "user": {"user_id": uid, "name": "Ana Ruiz"},
        "event": {"event_id": event_id, "name": "HackTX team-up", "type": "structured",
                  "tone": "casual", "description": "Find your hackathon team"},
        "questions": [{"question_id": q1, "text": "What role do you want?"},
                      {"question_id": q2, "text": "What do you want to build?"}],
        "profile_so_far": {
            "answers": {q1: "frontend", q2: "climate apps"},
            "fields": {"skills": ["react", "figma"], "experience_level": "intermediate"},
            "social_notes": "GitHub: 40 repos, mostly React",
        },
        "max_minutes": 5,
    }
    row = token_row(db, token)
    assert row.used_at is not None and timedelta(0) <= utcnow() - row.used_at < timedelta(minutes=1)


def test_summary_updates_profile_and_every_event_text(client, interview, db, text_changed, login_as):
    ana, event_id, token = interview
    uid = ana.user["user_id"]
    other = create(other_host(login_as), informal())  # a second event Ana is also in
    assert ana.post(f"/api/events/{other}/join", json={}).status_code == 201
    text_changed.clear()

    db.expire_all()
    before = {m.id: m.profile_text for m in db.exec(select(EventMember)).all()}
    assert all("Interview summary" not in t for t in before.values())

    assert config(client, token).status_code == 200
    resp = post_summary(client, token)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    db.expire_all()
    profile = db.exec(select(Profile).where(Profile.user_id == uid)).one()
    assert profile.summary == SUMMARY["summary"]
    assert profile.traits == SUMMARY["traits"]
    assert profile.transcript == SUMMARY["transcript"]
    assert profile.interview_input_mode == "voice"
    assert token_row(db, token) is None  # consumed

    members = db.exec(select(EventMember).where(EventMember.user_id == uid)).all()
    assert len(members) == 2
    for m in members:
        assert m.profile_text != before[m.id]
        assert f"Interview summary: {SUMMARY['summary']}" in m.profile_text
    # Both rebuilt texts were handed to the re-embedding hook, once.
    assert text_changed == [sorted(m.id for m in members)]


def test_failing_hook_never_fails_the_summary(client, interview, db, monkeypatch):
    def boom(ids):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(profile_svc, "on_member_text_changed", boom)
    _, _, token = interview
    config(client, token)
    assert post_summary(client, token).status_code == 200
    db.expire_all()
    assert db.exec(select(Profile)).one().summary == SUMMARY["summary"]


@pytest.mark.parametrize("change", [
    {"summary": "   "},
    {"summary": None},
    {"transcript": [{"role": "system", "text": "hi"}]},
    {"input_mode": "video"},
    {"traits": {"notes": "x" * 20_000}},
])
def test_invalid_summary_body_is_422(client, interview, db, change):
    _, _, token = interview
    config(client, token)
    assert_error(post_summary(client, token, {**SUMMARY, **change}), 422, "validation_error")
    assert token_row(db, token) is not None  # nothing consumed
