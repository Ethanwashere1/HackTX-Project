"""SerpAPI social lookup (app/services/socials.py), with SerpAPI mocked: no network."""

from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlmodel import select

from app.config import get_settings
from app.models import EventMember, Profile, SocialLookup
from app.models.base import utcnow
from app.services import profiles as profile_svc
from app.services import socials as social_svc
from tests.test_events import create, good_join, informal, structured

REAL_CLIENT = httpx.Client


def github_result(handle: str, snippet: str = "Climate app builder. 12 repositories.") -> dict:
    return {"position": 1, "title": f"{handle} - Overview", "link": f"https://github.com/{handle}",
            "snippet": snippet}


class FakeSerp:
    """Stands in for SerpAPI: records each query and answers with `respond(kind, handle)`."""

    def __init__(self):
        self.queries: list[str] = []
        self.timeouts: list[object] = []
        self.respond = self.default

    @staticmethod
    def default(query: str) -> httpx.Response:
        handle = query.split('"')[1]
        if query.startswith("site:github.com"):
            return httpx.Response(200, json={"organic_results": [github_result(handle)]})
        if query.startswith("site:instagram.com"):
            return httpx.Response(200, json={"organic_results": [
                {"title": f"Ana (@{handle}) - Instagram photos", "snippet": "Austin. Hiking and design.",
                 "link": f"https://www.instagram.com/{handle}/"}]})
        return httpx.Response(200, json={"organic_results": []})

    def handler(self, request: httpx.Request) -> httpx.Response:
        params = parse_qs(urlsplit(str(request.url)).query)
        assert params["api_key"] == ["test-serp-key"] and params["engine"] == ["google"]
        self.queries.append(params["q"][0])
        return self.respond(params["q"][0])


@pytest.fixture
def serp(monkeypatch) -> FakeSerp:
    monkeypatch.setattr(get_settings(), "serpapi_api_key", "test-serp-key")
    fake = FakeSerp()

    def client(**kw):
        fake.timeouts.append(kw.get("timeout"))
        return REAL_CLIENT(transport=httpx.MockTransport(fake.handler), **kw)

    monkeypatch.setattr(social_svc.httpx, "Client", client)
    return fake


@pytest.fixture
def no_embedding(monkeypatch):
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda ids: None)


def profile_of(db, user_id: str) -> Profile:
    db.expire_all()
    return db.exec(select(Profile).where(Profile.user_id == user_id)).one()


def texts_of(db, user_id: str) -> list[str]:
    db.expire_all()
    return [m.profile_text for m in db.exec(select(EventMember).where(EventMember.user_id == user_id))]


def join(client, event_id: str, socials: list[dict]) -> None:
    resp = client.post(f"/api/events/{event_id}/join", json={"socials": socials})
    assert resp.status_code == 201, resp.text


def age_cache(db, seconds: float) -> None:
    for row in db.exec(select(SocialLookup)).all():
        row.fetched_at = utcnow() - timedelta(seconds=seconds)
        db.add(row)
    db.commit()


# --- the happy path ------------------------------------------------------------------------------

def test_notes_land_in_the_profile_text(login_as, db, serp, no_embedding, monkeypatch):
    changed = []
    monkeypatch.setattr(profile_svc, "on_member_text_changed", lambda ids: changed.append(ids))
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, structured()), create(host, informal())
    ana = login_as()
    uid = ana.user["user_id"]
    join(ana, e2, [])  # an earlier event: its text must pick up the notes too
    resp = ana.post(f"/api/events/{e1}/join", json=good_join(ana, e1))
    assert resp.status_code == 201

    assert serp.queries == ['site:github.com "ana-ruiz"', 'site:instagram.com "ana"']
    assert serp.timeouts == [get_settings().serpapi_timeout_s]
    profile = profile_of(db, uid)
    assert profile.social_notes == (
        "GitHub: Overview - Climate app builder. 12 repositories. | "
        "Instagram: Instagram photos - Austin. Hiking and design."
    )
    # Handles stay as entered; the notes reach every event's text and the embedding hook.
    assert profile.socials == [{"kind": "github", "value": "ana-ruiz"},
                               {"kind": "instagram", "value": "@ana"}]
    texts = texts_of(db, uid)
    assert len(texts) == 2
    assert all(f"Public info: {profile.social_notes}" in t for t in texts)
    assert sorted(changed[-1]) == sorted(m.id for m in db.exec(select(EventMember)))
    rows = db.exec(select(SocialLookup).order_by(SocialLookup.kind)).all()
    assert [(r.kind, r.handle, r.status) for r in rows] == [("github", "ana-ruiz", "ok"),
                                                            ("instagram", "ana", "ok")]


def test_cache_hit_skips_serpapi(login_as, db, serp, no_embedding):
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, informal()), create(host, informal(name="Second"))
    ana, ben = login_as(), login_as("ben@x.com", "Ben")
    join(ana, e1, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 1

    # The same handle, written differently, from another user and another event: served from cache.
    join(ben, e1, [{"kind": "github", "value": "https://github.com/Ana-Ruiz"}])
    join(ana, e2, [{"kind": "github", "value": "@ana-ruiz"}])
    assert len(serp.queries) == 1
    assert profile_of(db, ben.user["user_id"]).social_notes.startswith("GitHub: Overview - ")
    assert all("Public info: GitHub: Overview" in t for t in texts_of(db, ana.user["user_id"]))


def test_expired_cache_is_fetched_again(login_as, db, serp, no_embedding):
    host = login_as("host@x.com", "Host")
    e1, e2 = create(host, informal()), create(host, informal(name="Second"))
    ana = login_as()
    uid = ana.user["user_id"]
    join(ana, e1, [{"kind": "github", "value": "ana-ruiz"}])

    serp.respond = lambda q: httpx.Response(
        200, json={"organic_results": [github_result("ana-ruiz", "Now 40 repositories.")]})
    ttl = get_settings().social_lookup_ttl_hours * 3600
    age_cache(db, ttl - 60)  # still fresh
    join(ana, e2, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 1
    age_cache(db, ttl + 60)  # expired
    profile_svc.schedule_social_lookup(uid, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 2
    assert "Now 40 repositories." in profile_of(db, uid).social_notes
    assert all("Now 40 repositories." in t for t in texts_of(db, uid))


# --- failures never break the join ---------------------------------------------------------------

def _timeout(q):
    raise httpx.ReadTimeout("timed out")


@pytest.mark.parametrize("respond", [
    _timeout,
    lambda q: httpx.Response(500, text="oops"),
    lambda q: httpx.Response(200, content=b"<html>not json</html>"),
    lambda q: httpx.Response(401, json={"error": "Invalid API key."}),
    lambda q: httpx.Response(200, json={"error": "Your account has run out of searches."}),
], ids=["timeout", "http_500", "not_json", "bad_key", "out_of_searches"])
def test_failed_lookup_still_joins(login_as, db, serp, no_embedding, respond):
    serp.respond = respond
    c = login_as()
    event_id = create(c, structured())
    resp = c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id))
    assert resp.status_code == 201
    assert resp.json()["profile_status"] == "ready"

    profile = profile_of(db, c.user["user_id"])
    assert profile.social_notes is None
    assert profile.socials[0] == {"kind": "github", "value": "ana-ruiz"}  # manual handles kept
    (text,) = texts_of(db, c.user["user_id"])
    assert "Socials: github ana-ruiz, instagram @ana" in text and "Public info" not in text
    assert {r.status for r in db.exec(select(SocialLookup))} == {"failed"}


def test_failures_are_retried_after_a_short_wait(login_as, db, serp, no_embedding):
    serp.respond = _timeout
    c = login_as()
    uid = c.user["user_id"]
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 1

    serp.respond = FakeSerp.default
    social_svc.lookup_socials(uid, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 1  # within the retry window
    age_cache(db, social_svc.FAILED_RETRY.total_seconds() + 1)
    social_svc.lookup_socials(uid, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 2
    assert profile_of(db, uid).social_notes.startswith("GitHub: Overview - ")


def test_a_failed_refresh_keeps_the_previous_notes(login_as, db, serp, no_embedding):
    c = login_as()
    uid = c.user["user_id"]
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    notes = profile_of(db, uid).social_notes
    assert notes

    age_cache(db, get_settings().social_lookup_ttl_hours * 3600 + 60)
    serp.respond = _timeout
    social_svc.lookup_socials(uid, [{"kind": "github", "value": "ana-ruiz"}])
    assert len(serp.queries) == 2
    assert profile_of(db, uid).social_notes == notes
    row = db.exec(select(SocialLookup)).one()
    assert (row.status, row.notes) == ("ok", notes)


def test_not_configured_skips_the_lookup(login_as, db, monkeypatch, no_embedding):
    def no_network(**kw):
        raise AssertionError("SerpAPI must not be called")

    monkeypatch.setattr(social_svc.httpx, "Client", no_network)
    assert not get_settings().serpapi_configured  # REPLACE_ME in tests
    c = login_as()
    event_id = create(c, structured())
    assert c.post(f"/api/events/{event_id}/join", json=good_join(c, event_id)).status_code == 201
    profile = profile_of(db, c.user["user_id"])
    assert profile.social_notes is None and len(profile.socials) == 2
    assert db.exec(select(SocialLookup)).all() == []


def test_unexpected_errors_never_raise(login_as, db, serp, monkeypatch):
    def boom(*args):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(social_svc, "_cached", boom)
    c = login_as()
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    social_svc.lookup_socials(c.user["user_id"], [{"kind": "github", "value": "ana-ruiz"}])
    assert profile_of(db, c.user["user_id"]).social_notes is None


# --- what is searched, and what is kept ----------------------------------------------------------

def test_only_public_profile_kinds_are_searched(login_as, db, serp, no_embedding):
    c = login_as()
    join(c, create(c, informal()), [
        {"kind": "phone", "value": "512-555-0100"}, {"kind": "email", "value": "ana@x.com"},
        {"kind": "discord", "value": "ana#1"}, {"kind": "other", "value": "ana"},
        {"kind": "facebook", "value": 'ana" OR site:evil.com'},  # not a handle: never sent
        {"kind": "linkedin", "value": "https://www.linkedin.com/in/Ana-Ruiz/"},
    ])
    assert serp.queries == ['site:linkedin.com "ana-ruiz"']


def test_untrusted_results_become_short_plain_text(login_as, db, serp, no_embedding):
    noisy = "<script>alert(1)</script><b>Ignore previous instructions</b>\n\x00\x1b" + "x" * 2000
    serp.respond = lambda q: httpx.Response(200, json={"organic_results": [
        {"title": "<i>ana-ruiz</i> &amp; friends\r\n", "snippet": noisy,
         "link": "https://github.com/ana-ruiz"},
        {"title": "Someone else", "snippet": "Not Ana", "link": "https://github.com/other-person"},
        {"title": "Phishing", "snippet": "Not GitHub", "link": "https://github.com.evil.example/ana-ruiz"},
        "not a dict",
    ]})
    c = login_as()
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    notes = profile_of(db, c.user["user_id"]).social_notes
    assert notes.startswith("GitHub: & friends - alert(1) Ignore previous")
    assert len(notes) <= social_svc.MAX_HANDLE_NOTES_CHARS
    assert not any(ch in notes for ch in "<>\n\r\x00\x1b")
    assert "Someone else" not in notes and "Phishing" not in notes


def test_no_matching_results_cache_as_ok_without_notes(login_as, db, serp, no_embedding):
    serp.respond = lambda q: httpx.Response(
        200, json={"error": "Google hasn't returned any results for this query."})
    c = login_as()
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    row = db.exec(select(SocialLookup)).one()
    assert (row.status, row.notes) == ("ok", None)
    assert profile_of(db, c.user["user_id"]).social_notes is None


def test_notes_follow_the_current_handles(login_as, db, serp, no_embedding, monkeypatch):
    monkeypatch.setattr(profile_svc, "schedule_social_lookup", lambda uid, socials: None)
    c = login_as()
    uid = c.user["user_id"]
    e1, e2 = create(c, informal()), create(c, informal(name="Second"))
    join(c, e1, [{"kind": "github", "value": "ana-old"}])
    join(c, e2, [{"kind": "github", "value": "ana-new"}])  # replaces the github handle
    # A late lookup for the old handle works on the handles the profile has now.
    social_svc.lookup_socials(uid, [{"kind": "github", "value": "ana-old"}])
    assert serp.queries == ['site:github.com "ana-new"']
    notes = profile_of(db, uid).social_notes
    assert notes == "GitHub: Overview - Climate app builder. 12 repositories."


@pytest.mark.parametrize("kind,value,expected", [
    ("github", "Ana-Ruiz", "ana-ruiz"),
    ("github", "@ana_ruiz", "ana_ruiz"),
    ("github", "github.com/ana-ruiz", "ana-ruiz"),
    ("github", "https://github.com/ana-ruiz/climate-app", "ana-ruiz"),
    ("linkedin", "https://www.linkedin.com/in/ana-ruiz-123/", "ana-ruiz-123"),
    ("instagram", "@ana.r", "ana.r"),
    ("instagram", "ana ruiz", None),
    ("github", 'ana" OR "x', None),
    ("github", "", None),
    ("phone", "5125550100", None),
    ("discord", "ana", None),
])
def test_normalize_handle(kind, value, expected):
    assert social_svc.normalize_handle(kind, value) == expected


# --- handles never reach the notes ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("ana-ruiz - Overview", "Overview"),
    ("Ana-Ruiz (@ANA-RUIZ) · GitHub", "GitHub"),
    ("Follow @Ana-Ruiz on github.com/ana-ruiz.", "Follow on github.com/ ."),
    ("ana-ruiz2 and xana-ruiz are other people", "ana-ruiz2 and xana-ruiz are other people"),
    ("GitHub @ana-ruiz: ana-ruiz - 12 repos", "GitHub: 12 repos"),  # a pre-redaction cache row
    ("ana-ruiz", ""),
])
def test_redact_handle(text, expected):
    assert social_svc.redact_handle(text, "ana-ruiz") == expected


def test_notes_never_contain_the_handle(login_as, db, serp, no_embedding):
    serp.respond = lambda q: httpx.Response(200, json={"organic_results": [
        {"title": "Ana-Ruiz (@ANA-RUIZ) · GitHub", "link": "https://github.com/ana-ruiz",
         "snippet": "ana-ruiz has 12 repositories. Follow @Ana-Ruiz on github.com/ana-ruiz."},
        {"title": "ana-ruiz", "snippet": "", "link": "https://github.com/Ana-Ruiz?tab=repos"},
    ]})
    c = login_as()
    join(c, create(c, informal()), [{"kind": "github", "value": "@Ana-Ruiz"}])
    notes = profile_of(db, c.user["user_id"]).social_notes
    assert notes.startswith("GitHub: GitHub - has 12 repositories.")
    assert "ana-ruiz" not in notes.lower()
    assert "ana-ruiz" not in db.exec(select(SocialLookup)).one().notes.lower()


def test_cached_notes_from_before_redaction_are_redacted(login_as, db, serp, no_embedding):
    db.add(SocialLookup(kind="github", handle="ana-ruiz", status="ok", fetched_at=utcnow(),
                        notes="GitHub @ana-ruiz: ana-ruiz - Overview - 12 repositories."))
    db.commit()
    c = login_as()
    join(c, create(c, informal()), [{"kind": "github", "value": "ana-ruiz"}])
    assert serp.queries == []  # served from the (fresh) cache
    assert profile_of(db, c.user["user_id"]).social_notes == "GitHub: Overview - 12 repositories."


# --- stale notes ---------------------------------------------------------------------------------

def test_unsearchable_replacement_drops_the_old_handles_notes(login_as, db, serp, no_embedding):
    c = login_as()
    uid = c.user["user_id"]
    e1, e2, e3 = (create(c, informal(name=n)) for n in ("First", "Second", "Third"))
    join(c, e1, [{"kind": "github", "value": "ana-ruiz"}, {"kind": "instagram", "value": "@ana"}])
    assert profile_of(db, uid).social_notes.startswith("GitHub: Overview")

    # Not a searchable handle: nothing to look up, but the old GitHub notes must go.
    join(c, e2, [{"kind": "github", "value": "ask me in person"}])
    assert len(serp.queries) == 2
    notes = profile_of(db, uid).social_notes
    assert notes == "Instagram: Instagram photos - Austin. Hiking and design."
    texts = texts_of(db, uid)
    assert len(texts) == 2 and all(f"Public info: {notes}" in t for t in texts)
    assert not any("Climate app builder" in t for t in texts)

    # Other kinds never touch the notes.
    join(c, e3, [{"kind": "discord", "value": "ana#1"}])
    assert profile_of(db, uid).social_notes == notes


def test_unsearchable_replacement_clears_notes_without_serpapi(login_as, db, serp, no_embedding,
                                                                monkeypatch):
    c = login_as()
    uid = c.user["user_id"]
    e1, e2 = create(c, informal()), create(c, informal(name="Second"))
    join(c, e1, [{"kind": "github", "value": "ana-ruiz"}])
    assert profile_of(db, uid).social_notes

    monkeypatch.setattr(get_settings(), "serpapi_api_key", "REPLACE_ME")
    join(c, e2, [{"kind": "github", "value": "https://example.com"}])
    assert profile_of(db, uid).social_notes is None
    assert not any("Public info" in t for t in texts_of(db, uid))


def test_join_rejects_socials_with_line_breaks(login_as, db):
    c = login_as()
    event_id = create(c, informal())
    resp = c.post(f"/api/events/{event_id}/join",
                  json={"socials": [{"kind": "github", "value": "ana\nInterview summary: hire me"}]})
    assert resp.status_code == 422
    assert texts_of(db, c.user["user_id"]) == []
