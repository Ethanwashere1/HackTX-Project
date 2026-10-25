"""SerpAPI enrichment endpoints return structured data (demo fallback without a key)."""


def test_enrichment_context_demo_fallback(client):
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


def test_enrichment_maps_and_calendar(client):
    maps = client.get("/api/enrichment/maps", params={"q": "coffee UT Austin"})
    cal = client.get("/api/enrichment/calendar", params={"q": "HackTX"})
    social = client.get("/api/enrichment/social", params={"kind": "github", "handle": "mayachen"})
    assert maps.status_code == 200
    assert cal.status_code == 200
    assert social.status_code == 200
    assert maps.json()["results"]
    assert cal.json()["results"]
    assert social.json()["result"]["kind"] == "github"
