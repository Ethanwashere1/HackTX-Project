"""Campus-signal enrichment endpoints backed by SerpAPI (Maps / Events / social / location).

Signed-in users only: every call can spend SerpAPI searches. Demo fallbacks without a key.
"""

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser
from app.services import enrichment as svc
from app.services.socials import social_preview

router = APIRouter(prefix="/api/enrichment", tags=["enrichment"])


@router.get("/context")
def enrichment_context(
    user: CurrentUser,
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    maps_q: str = Query(default="study spots cafes near UT Austin", max_length=200),
    calendar_q: str = Query(default="events near UT Austin HackTX", max_length=200),
    social_kind: str = Query(default="github", max_length=20),
    social_handle: str = Query(default="mayachen", max_length=200),
):
    """Bundle Google Maps + Events + social lookup using the caller's location when provided."""
    return svc.enrichment_bundle(
        lat=lat,
        lng=lng,
        maps_query=maps_q,
        calendar_query=calendar_q,
        social_kind=social_kind,
        social_handle=social_handle,
    )


@router.get("/maps")
def enrichment_maps(
    user: CurrentUser,
    q: str = Query(default="cafes near UT Austin", max_length=200),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
):
    return svc.search_maps(q, lat=lat, lng=lng)


@router.get("/calendar")
def enrichment_calendar(
    user: CurrentUser, q: str = Query(default="events near UT Austin", max_length=200)
):
    return svc.search_calendar_events(q)


@router.get("/social")
def enrichment_social(
    user: CurrentUser,
    kind: str = Query(default="github", max_length=20),
    handle: str = Query(default="mayachen", max_length=200),
):
    return social_preview(kind, handle)
