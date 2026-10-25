"""Public enrichment endpoints backed by SerpAPI (Maps / Events / social / location)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.services import serpapi

router = APIRouter(prefix="/api/enrichment", tags=["enrichment"])


@router.get("/context")
async def enrichment_context(
    lat: float | None = Query(default=None),
    lng: float | None = Query(default=None),
    maps_q: str = Query(default="study spots cafes near UT Austin"),
    calendar_q: str = Query(default="events near UT Austin HackTX"),
    social_kind: str = Query(default="github"),
    social_handle: str = Query(default="mayachen"),
):
    """Bundle Google Maps + Events + social lookup using the caller's location when provided."""
    return await serpapi.enrichment_bundle(
        lat=lat,
        lng=lng,
        maps_query=maps_q,
        calendar_query=calendar_q,
        social_kind=social_kind,
        social_handle=social_handle,
    )


@router.get("/maps")
async def enrichment_maps(
    q: str = Query(default="cafes near UT Austin"),
    lat: float | None = None,
    lng: float | None = None,
):
    return await serpapi.search_maps(q, lat=lat, lng=lng)


@router.get("/calendar")
async def enrichment_calendar(q: str = Query(default="events near UT Austin")):
    return await serpapi.search_calendar_events(q)


@router.get("/social")
async def enrichment_social(
    kind: str = Query(default="github"),
    handle: str = Query(default="mayachen"),
):
    return await serpapi.lookup_social(kind, handle)
