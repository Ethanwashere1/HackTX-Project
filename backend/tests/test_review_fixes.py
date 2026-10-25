"""Config safety, the test-DB guard, account linking, session cleanup and OAuth callback edges."""

from datetime import timedelta

import httpx
import pytest
from fastapi import Response
from sqlmodel import select

from app.auth import google
from app.auth.sessions import set_session_cookie
from app.config import DEV_SESSION_SECRET, Settings
from app.models import User, UserSession
from app.models.base import utcnow
from app.services import users as users_svc
from tests.conftest import unsafe_test_database_reason
from tests.test_auth import google_configured, mock_google, start_login  # noqa: F401
from tests.test_health_errors import assert_error

REAL_ASYNC_CLIENT = httpx.AsyncClient

# --- config --------------------------------------------------------------------------------------


def make_settings(monkeypatch, **kw) -> Settings:
    """Settings from explicit values only (no backend/.env, no APP_ENV from the test env)."""
    monkeypatch.delenv("APP_ENV", raising=False)
    return Settings(_env_file=None, **kw)


def test_app_env_defaults_to_production(monkeypatch):
    s = make_settings(monkeypatch, session_secret="a-real-secret")
    assert s.app_env == "production" and not s.is_local


@pytest.mark.parametrize("secret", ["", "REPLACE_ME", DEV_SESSION_SECRET])
def test_production_refuses_to_start_without_real_secret(monkeypatch, secret):
    s = make_settings(monkeypatch, app_env="production", session_secret=secret)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        s.check_startup()


def test_production_starts_with_real_secret(monkeypatch):
    make_settings(monkeypatch, app_env="production", session_secret="s3cret-value").check_startup()


def test_local_starts_with_dev_secret(monkeypatch):
    s = make_settings(monkeypatch, app_env="local")
    s.check_startup()
    assert s.effective_session_secret == DEV_SESSION_SECRET


def test_embedding_dim_must_match_schema(monkeypatch):
    s = make_settings(monkeypatch, app_env="local", embedding_dim=1536)
    with pytest.raises(RuntimeError, match="EMBEDDING_DIM"):
        s.check_startup()


@pytest.mark.parametrize(
    "env,flag,secure",
    [("production", False, True), ("staging", False, True), ("local", False, False),
     ("test", False, False), ("local", True, True)],
)
def test_cookie_secure_outside_local(monkeypatch, env, flag, secure):
    s = make_settings(monkeypatch, app_env=env, session_cookie_secure=flag)
    assert s.cookie_secure is secure


def test_session_cookie_is_secure_in_production(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    resp = Response()
    set_session_cookie(resp, "tok")
    assert "secure" in resp.headers["set-cookie"].lower()


# --- destructive test-DB guard -------------------------------------------------------------------

@pytest.mark.parametrize(
    "test_url,app_url,refused",
    [
        ("postgresql://u@localhost:5432/squadup", None, True),  # name lacks "test"
        ("postgresql+psycopg://a@127.0.0.1/app_test", "postgres://b:pw@localhost:5432/app_test", True),
        ("postgresql://a@db.example.com:6543/app_test", "postgresql://a@DB.example.com:6543/app_test", True),
        ("postgresql://a@localhost:5433/app_test", "postgresql://a@localhost:5432/app_test", False),
        ("postgresql://a@localhost/app_test", "postgresql://a@localhost/app", False),
        ("postgresql://a@localhost/squadup_test", None, False),
    ],
)
def test_test_database_guard(test_url, app_url, refused):
    assert (unsafe_test_database_reason(test_url, app_url) is not None) is refused


# --- account linking -----------------------------------------------------------------------------

def google_login(client, monkeypatch, sub: str, email: str):
    monkeypatch.setattr(httpx, "AsyncClient", REAL_ASYNC_CLIENT)  # mock_google wraps whatever is there
    mock_google(monkeypatch, {"sub": sub, "email": email, "email_verified": True, "name": "X"})
    _, state = start_login(client)
    return client.get(
        "/api/auth/google/callback", params={"code": "good-code", "state": state},
        follow_redirects=False,
    )


def test_google_login_links_existing_email_without_sub(client, login_as, google_configured, monkeypatch, db):
    existing = login_as("ana@utexas.edu", "Ana").user["user_id"]
    resp = google_login(client, monkeypatch, "g-1", "ana@utexas.edu")
    assert resp.status_code == 302, resp.text
    assert client.get("/api/me").json()["user_id"] == existing
    assert db.get(User, existing).google_sub == "g-1"


def test_google_login_never_takes_over_email_linked_to_other_sub(
    client, google_configured, monkeypatch, db
):
    assert google_login(client, monkeypatch, "g-1", "ana@utexas.edu").status_code == 302
    client.cookies.clear()
    resp = google_login(client, monkeypatch, "g-2", "ana@utexas.edu")
    assert_error(resp, 409, "account_conflict")
    users = db.exec(select(User)).all()
    assert [(u.email, u.google_sub) for u in users] == [("ana@utexas.edu", "g-1")]
    assert_error(client.get("/api/me"), 401, "unauthenticated")


def test_email_collision_on_update_is_409_not_500(client, login_as, google_configured, monkeypatch):
    assert google_login(client, monkeypatch, "g-1", "ana@utexas.edu").status_code == 302
    login_as("ben@utexas.edu", "Ben")
    client.cookies.clear()
    # Google account g-1 now reports Ben's email: the unique email index rejects it cleanly.
    assert_error(google_login(client, monkeypatch, "g-1", "ben@utexas.edu"), 409, "account_conflict")


def test_racing_first_login_reuses_the_winning_row(db, monkeypatch):
    winner = users_svc.upsert_user(db, email="ana@utexas.edu", name="Ana", google_sub="g-1")
    real = users_svc._find_or_build
    calls = []

    def stale_lookup(*args, **kwargs):
        # The first lookup ran before the other request committed, so it builds a duplicate.
        calls.append(1)
        if len(calls) == 1:
            return User(email="ana@utexas.edu", name="Ana", google_sub="g-1")
        return real(*args, **kwargs)

    monkeypatch.setattr(users_svc, "_find_or_build", stale_lookup)
    user = users_svc.upsert_user(db, email="ana@utexas.edu", name="Ana", google_sub="g-1")
    assert user.id == winner.id and len(calls) == 2


# --- session cleanup -----------------------------------------------------------------------------

def test_login_deletes_expired_sessions(login_as, db):
    user_id = login_as("ana@utexas.edu").user["user_id"]
    now = utcnow()
    db.add(UserSession(token_hash="e" * 64, user_id=user_id, created_at=now - timedelta(days=30),
                       expires_at=now - timedelta(days=1)))
    db.commit()
    login_as("ana@utexas.edu")
    db.expire_all()
    rows = db.exec(select(UserSession).where(UserSession.user_id == user_id)).all()
    assert len(rows) == 2 and all(r.expires_at > now for r in rows)


# --- OAuth callback edges ------------------------------------------------------------------------

def state_cookie_cleared(resp) -> bool:
    return any(
        c.startswith("oauth_state=") and "Max-Age=0" in c for c in resp.headers.get_list("set-cookie")
    )


def test_callback_missing_code_is_400_bad_request(client, google_configured):
    _, state = start_login(client)
    resp = client.get("/api/auth/google/callback", params={"state": state}, follow_redirects=False)
    assert_error(resp, 400, "bad_request")
    assert state_cookie_cleared(resp)


def test_callback_non_json_google_response_is_502(client, google_configured, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>oops</html>")

    real = httpx.AsyncClient
    monkeypatch.setattr(
        google.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    _, state = start_login(client)
    resp = client.get(
        "/api/auth/google/callback", params={"code": "good-code", "state": state},
        follow_redirects=False,
    )
    assert_error(resp, 502, "oauth_failed")
    assert state_cookie_cleared(resp)


def test_callback_clears_state_cookie_on_every_response(client, google_configured, monkeypatch):
    start_login(client)
    bad = client.get("/api/auth/google/callback", params={"code": "c", "state": "forged"},
                     follow_redirects=False)
    assert bad.status_code == 400 and state_cookie_cleared(bad)

    cancel = client.get("/api/auth/google/callback", params={"error": "access_denied"},
                        follow_redirects=False)
    assert cancel.status_code == 302 and state_cookie_cleared(cancel)

    ok = google_login(client, monkeypatch, "g-9", "zed@utexas.edu")
    assert ok.status_code == 302 and state_cookie_cleared(ok)
