"""SerpAPI enrichment endpoints return structured data (demo fallback without a key)."""

import httpx

from app.config import get_settings
from app.services import enrichment
from tests.test_health_errors import assert_error


def test_enrichment_requires_login(client):
    # Adapted from main: every call can spend SerpAPI searches, so signed-in users only.
    for path in ("context", "maps", "calendar", "social"):
        assert_error(client.get(f"/api/enrichment/{path}"), 401, "unauthenticated")


def test_enrichment_context_demo_fallback(login_as):
    client = login_as()
    res = client.get("/api/enrichment/context")
    assert res.status_code == 200
    body = res.json()
    assert "maps" in body and "calendar" in body and "social" in body
    assert "location" in body
    assert body["maps"]["engine"] == "google_maps"
    assert body["calendar"]["engine"] == "google_events"
    assert body["maps"]["source"] in ("demo_fallback", "serpapi")
    assert len(body["maps"]["results"]) >= 1
    assert len(body["calendar"]["results"]) >= 1
    assert body["social"]["result"]["handle"]


def test_enrichment_maps_and_calendar(login_as):
    client = login_as()
    maps = client.get("/api/enrichment/maps", params={"q": "coffee UT Austin"})
    cal = client.get("/api/enrichment/calendar", params={"q": "HackTX"})
    social = client.get("/api/enrichment/social", params={"kind": "github", "handle": "mayachen"})
    assert maps.status_code == 200
    assert cal.status_code == 200
    assert social.status_code == 200
    assert maps.json()["results"]
    assert cal.json()["results"]
    assert social.json()["result"]["kind"] == "github"


def test_enrichment_through_serpapi_with_cache(login_as, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        engine = request.url.params["engine"]
        if engine == "google_maps":
            return httpx.Response(200, json={"local_results": [
                {"title": "PCL", "address": "101 E 21st St", "rating": 4.6, "type": "library",
                 "gps_coordinates": {"latitude": 30.28, "longitude": -97.73}}]})
        if engine == "google_events":
            return httpx.Response(200, json={"events_results": [
                {"title": "HackTX", "date": {"when": "Sat"}, "venue": {"name": "GDC"}, "link": "https://x"}]})
        return httpx.Response(200, json={"organic_results": [
            {"title": "someone-else", "link": "https://github.com/someone-else", "snippet": "no"},
            {"title": "Maya Chen", "link": "https://github.com/mayachen", "snippet": "Builds <b>tools</b>"}]})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(get_settings(), "serpapi_api_key", "test-serp-key")
    enrichment._cache.clear()
    client = login_as()
    params = {"lat": 30.28491, "lng": -97.73412}
    body = client.get("/api/enrichment/context", params=params).json()
    assert body["serpapi_configured"] is True
    assert body["maps"] == {"source": "serpapi", "engine": "google_maps", "results": [
        {"title": "PCL", "address": "101 E 21st St", "rating": 4.6, "type": "library",
         "maps_url": "https://maps.google.com/?q=30.28,-97.73"}]}
    assert body["calendar"]["results"] == [{"title": "HackTX", "date": "Sat", "venue": "GDC", "link": "https://x"}]
    assert body["social"]["source"] == "serpapi"
    assert body["social"]["result"]["profile_url"] == "https://github.com/mayachen"
    assert body["social"]["result"]["bio"] == "Builds tools"
    assert [c["engine"] for c in calls] == ["google_maps", "google_events", "google"]
    assert calls[0]["ll"] == "@30.285,-97.734,14z"
    assert calls[2]["q"] == 'site:github.com "mayachen"'
    # Maps and events answers are cached; the social preview is not.
    client.get("/api/enrichment/context", params=params)
    assert [c["engine"] for c in calls[3:]] == ["google"]
    enrichment._cache.clear()
