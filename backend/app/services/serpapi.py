"""SerpAPI client for Maps, Events (calendar-like), social search, and nearby places.

When SERPAPI_API_KEY is missing or a call fails, callers get structured demo fallbacks
so the product demo never hard-depends on the live key.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

SERPAPI_BASE = "https://serpapi.com/search.json"


def _demo_places(query: str, lat: float | None, lng: float | None) -> list[dict[str, Any]]:
    near = f"{lat:.4f},{lng:.4f}" if lat is not None and lng is not None else "UT Austin"
    return [
        {
            "title": "PCL (Perry-Castañeda Library)",
            "address": "101 E 21st St, Austin, TX",
            "rating": 4.6,
            "type": "library",
            "maps_url": "https://maps.google.com/?q=Perry-Castaneda+Library",
            "near": near,
            "query": query or "study spots near me",
        },
        {
            "title": "GDC (Gates Dell Complex)",
            "address": "2317 Speedway, Austin, TX",
            "rating": 4.7,
            "type": "university",
            "maps_url": "https://maps.google.com/?q=Gates+Dell+Complex",
            "near": near,
            "query": query or "hackathon venues",
        },
        {
            "title": "Spider House Cafe",
            "address": "2908 Fruth St, Austin, TX",
            "rating": 4.5,
            "type": "cafe",
            "maps_url": "https://maps.google.com/?q=Spider+House+Cafe",
            "near": near,
            "query": query or "coffee hangouts",
        },
    ]


def _demo_calendar(query: str) -> list[dict[str, Any]]:
    return [
        {
            "title": "HackTX Opening Ceremony",
            "date": "Sat, Oct 25 · 10:00 AM",
            "venue": "GDC Auditorium",
            "link": "https://hacktx.com",
            "query": query or "HackTX Austin",
        },
        {
            "title": "UTCS Career Fair",
            "date": "Tue, Oct 28 · 1:00 PM",
            "venue": "PCL",
            "link": "https://www.cs.utexas.edu",
            "query": query or "UT Austin events",
        },
        {
            "title": "Campus photo walk meetup",
            "date": "Sun, Oct 27 · 5:30 PM",
            "venue": "Main Mall",
            "link": "https://maps.google.com/?q=UT+Austin+Main+Mall",
            "query": query or "campus events Austin",
        },
    ]


def _demo_social(kind: str, handle: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "handle": handle,
        "display_name": handle.lstrip("@"),
        "bio": "Builder · UT Austin · open to HackTX squads",
        "profile_url": f"https://{kind}.com/{handle.lstrip('@')}",
        "notes": "Public profile signals: React, campus tools, climate apps.",
    }


async def _serpapi_get(params: dict[str, Any]) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.serpapi_configured:
        return None
    payload = {**params, "api_key": settings.serpapi_api_key}
    try:
        async with httpx.AsyncClient(timeout=settings.serpapi_timeout_s) as client:
            res = await client.get(SERPAPI_BASE, params=payload)
            res.raise_for_status()
            return res.json()
    except Exception:
        log.exception("SerpAPI request failed (%s)", params.get("engine"))
        return None


async def search_maps(
    query: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "engine": "google_maps",
        "q": query or "cafes near UT Austin",
        "type": "search",
    }
    if lat is not None and lng is not None:
        params["ll"] = f"@{lat},{lng},14z"

    data = await _serpapi_get(params)
    if not data:
        return {
            "source": "demo_fallback",
            "engine": "google_maps",
            "results": _demo_places(query, lat, lng),
        }

    raw = data.get("local_results")
    if not raw and data.get("place_results"):
        raw = [data["place_results"]]
    results = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        gps = item.get("gps_coordinates") or {}
        maps_url = item.get("link")
        if gps.get("latitude") is not None and gps.get("longitude") is not None:
            maps_url = (
                f"https://maps.google.com/?q={gps['latitude']},{gps['longitude']}"
            )
        types = item.get("types") or []
        results.append(
            {
                "title": item.get("title"),
                "address": item.get("address"),
                "rating": item.get("rating"),
                "type": item.get("type") or (types[0] if types else None),
                "maps_url": maps_url,
            }
        )
    return {"source": "serpapi", "engine": "google_maps", "results": results[:8]}


async def search_calendar_events(query: str) -> dict[str, Any]:
    """Google Events via SerpAPI — used as a campus/calendar signal for the demo."""
    data = await _serpapi_get(
        {
            "engine": "google_events",
            "q": query or "events near UT Austin",
        }
    )
    if not data:
        return {
            "source": "demo_fallback",
            "engine": "google_events",
            "results": _demo_calendar(query),
        }

    results = []
    for item in data.get("events_results") or []:
        results.append(
            {
                "title": item.get("title"),
                "date": (item.get("date") or {}).get("when")
                if isinstance(item.get("date"), dict)
                else item.get("date"),
                "venue": (item.get("venue") or {}).get("name")
                if isinstance(item.get("venue"), dict)
                else item.get("venue"),
                "link": item.get("link"),
            }
        )
    return {"source": "serpapi", "engine": "google_events", "results": results[:8]}


async def lookup_social(kind: str, handle: str) -> dict[str, Any]:
    q = f"{kind} {handle}".strip()
    data = await _serpapi_get({"engine": "google", "q": q})
    if not data:
        return {
            "source": "demo_fallback",
            "engine": "google",
            "result": _demo_social(kind, handle),
        }

    organic = (data.get("organic_results") or [{}])[0]
    result = {
        "kind": kind,
        "handle": handle,
        "display_name": organic.get("title") or handle,
        "bio": organic.get("snippet") or "",
        "profile_url": organic.get("link"),
        "notes": organic.get("snippet"),
    }
    return {"source": "serpapi", "engine": "google", "result": result}


async def enrichment_bundle(
    *,
    lat: float | None,
    lng: float | None,
    maps_query: str,
    calendar_query: str,
    social_kind: str,
    social_handle: str,
) -> dict[str, Any]:
    maps = await search_maps(maps_query, lat=lat, lng=lng)
    calendar = await search_calendar_events(calendar_query)
    social = await lookup_social(social_kind, social_handle)
    location = {
        "lat": lat,
        "lng": lng,
        "label": "Browser geolocation" if lat is not None else "Default · UT Austin campus",
        "fallback_lat": 30.2849,
        "fallback_lng": -97.7341,
    }
    return {
        "location": location,
        "maps": maps,
        "calendar": calendar,
        "social": social,
        "serpapi_configured": get_settings().serpapi_configured,
    }
