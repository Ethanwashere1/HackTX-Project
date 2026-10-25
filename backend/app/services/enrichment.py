"""Campus signals for the org feed (GET /api/enrichment/*): Google Maps places and Google Events
via SerpAPI, plus the social preview from app.services.socials.

SerpAPI requests go through socials.serpapi_search (the backend's one SerpAPI path). Answers are
cached in memory for CACHE_TTL so feed reloads don't spend searches. When SERPAPI_API_KEY is missing
or a call fails, callers get structured demo fallbacks so the demo never depends on the live key.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.config import get_settings
from app.services.socials import SerpApiError, serpapi_search, social_preview

log = logging.getLogger(__name__)

CACHE_TTL_S = 600
CACHE_MAX = 256
_cache: dict[tuple, tuple[float, dict[str, Any]]] = {}


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


def _serpapi_get(params: dict[str, Any]) -> dict[str, Any] | None:
    """The SerpAPI answer for `params` (cached), or None when not configured or on failure."""
    settings = get_settings()
    if not settings.serpapi_configured:
        return None
    key = tuple(sorted(params.items()))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    try:
        with httpx.Client(timeout=settings.serpapi_timeout_s) as client:
            data = serpapi_search(client, settings.serpapi_api_key, params)
    except SerpApiError as exc:
        log.warning("SerpAPI %s search failed: %s", params.get("engine"), exc)
        return None
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.monotonic(), data)
    return data


def search_maps(
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
        params["ll"] = f"@{lat:.3f},{lng:.3f},14z"  # ~100 m: enough for nearby, and caches better

    data = _serpapi_get(params)
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


def search_calendar_events(query: str) -> dict[str, Any]:
    """Google Events via SerpAPI — used as a campus/calendar signal for the demo."""
    data = _serpapi_get(
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


def enrichment_bundle(
    *,
    lat: float | None,
    lng: float | None,
    maps_query: str,
    calendar_query: str,
    social_kind: str,
    social_handle: str,
) -> dict[str, Any]:
    maps = search_maps(maps_query, lat=lat, lng=lng)
    calendar = search_calendar_events(calendar_query)
    social = social_preview(social_kind, social_handle)
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
