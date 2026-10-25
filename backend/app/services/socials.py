"""SerpAPI social lookup: public info about a user's social handles, distilled into
`profiles.social_notes` so it feeds the match text of every event the user is in.

Optional by design. It runs after the join response, skips while SERPAPI_API_KEY is not configured
or when SerpAPI fails, and the handles stay on the profile as entered either way. Results are cached
per (kind, handle) in social_lookups for SOCIAL_LOOKUP_TTL_HOURS; a failed call is retried after
FAILED_RETRY instead and never overwrites an earlier good result. Search results are untrusted web
text (they reach Gemini prompts via profile_text), so the notes are short plain text.

This module is also the backend's single SerpAPI HTTP path: serpapi_search() serves the profile
lookup here, the social preview (social_preview) and the maps/events enrichment
(app.services.enrichment).
"""

import html
import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from app.config import Settings, get_settings
from app.db import get_engine
from app.ids import new_id
from app.models import Profile, SocialLookup
from app.models.base import utcnow
from app.services.profiles import refresh_member_texts

log = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
# The contact kinds worth searching, with the site that hosts the profile. Phone, email, discord
# and "other" are never sent to SerpAPI.
SITES = {
    "github": "github.com",
    "linkedin": "linkedin.com",
    "instagram": "instagram.com",
    "facebook": "facebook.com",
}
LABELS = {"github": "GitHub", "linkedin": "LinkedIn", "instagram": "Instagram", "facebook": "Facebook"}
HANDLE_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,99}")
TAG_RE = re.compile(r"<[^>]*>")
EMPTY_BRACKETS_RE = re.compile(r"\(\s*\)|\[\s*\]")
MAX_HANDLES = 4  # SerpAPI calls per lookup, at most
RESULTS_PER_HANDLE = 2
MAX_HANDLE_NOTES_CHARS = 240
MAX_NOTES_CHARS = 600
FAILED_RETRY = timedelta(minutes=10)
NO_RESULTS_ERROR = "hasn't returned any results"

Handle = tuple[str, str]  # (kind, normalized handle)


class SerpApiError(Exception):
    """SerpAPI could not be queried or answered with an error."""


def _profile_segment(kind: str, path: str) -> str:
    """The path segment of a profile URL that holds the handle (linkedin.com/in/<handle>)."""
    segments = [s for s in path.split("/") if s]
    if kind == "linkedin" and len(segments) >= 2 and segments[0].lower() in ("in", "pub"):
        return segments[1]
    return segments[0] if segments else ""


def normalize_handle(kind: str, value: str) -> str | None:
    """The searchable handle for a submitted value ("@Ana", a profile URL, ...), or None."""
    if kind not in SITES:
        return None
    v = value.strip()
    if "/" in v:
        v = _profile_segment(kind, urlsplit(v if "://" in v else "https://" + v).path)
    v = v.lstrip("@").lower()
    return v if HANDLE_RE.fullmatch(v) else None


def searchable_handles(socials: list[dict[str, Any]]) -> list[Handle]:
    """Distinct searchable (kind, handle) pairs in submission order, at most MAX_HANDLES."""
    handles: list[Handle] = []
    for s in socials:
        handle = normalize_handle(str(s.get("kind", "")), str(s.get("value", "")))
        if handle and (s["kind"], handle) not in handles:
            handles.append((s["kind"], handle))
    return handles[:MAX_HANDLES]


def clean_text(value: Any, limit: int) -> str:
    """Untrusted web text as one short plain-text line: no markup, control characters or newlines."""
    text = TAG_RE.sub(" ", html.unescape(str(value or "")))
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def redact_handle(text: str, handle: str) -> str:
    """`text` without the handle (any case, with or without @). The notes reach places the
    handles themselves must not, such as the agents' prompts and match reasons."""
    pattern = re.compile(rf"(?<![\w.@-])@?{re.escape(handle)}(?![\w-]|\.\w)", re.IGNORECASE)
    text = EMPTY_BRACKETS_RE.sub(" ", pattern.sub(" ", text))
    text = re.sub(r"\s+(?=[:,])", "", " ".join(text.split()))  # "GitHub @ana: x" -> "GitHub: x"
    text = re.sub(r":\s*[-|·/]\s+", ": ", text)  # "GitHub: - Overview" -> "GitHub: Overview"
    return text.strip(" -|:/·,")


def _result_text(value: Any, handle: str, limit: int) -> str:
    # Cleaned in full before redacting, so truncation can't leave half a handle behind.
    return clean_text(redact_handle(clean_text(value, 10_000), handle), limit)


def distill(kind: str, handle: str, data: dict[str, Any]) -> str | None:
    """Short notes from the organic results that are this handle's own profile pages, labeled by
    site and with the handle redacted."""
    pieces: list[str] = []
    for result in data.get("organic_results") or []:
        if not isinstance(result, dict):
            continue
        link = urlsplit(str(result.get("link") or ""))
        host = (link.hostname or "").lower()
        if not (host == SITES[kind] or host.endswith("." + SITES[kind])):
            continue
        if _profile_segment(kind, link.path).lower() != handle:
            continue  # someone else's page, or not a profile
        title = _result_text(result.get("title"), handle, 100)
        snippet = _result_text(result.get("snippet"), handle, 160)
        piece = " - ".join(p for p in (title, snippet) if p)
        if piece and piece not in pieces:
            pieces.append(piece)
        if len(pieces) == RESULTS_PER_HANDLE:
            break
    if not pieces:
        return None
    return clean_text(f"{LABELS[kind]}: " + " / ".join(pieces), MAX_HANDLE_NOTES_CHARS)


def serpapi_search(client: httpx.Client, api_key: str, params: dict[str, Any]) -> dict[str, Any]:
    """One SerpAPI search: the response JSON. Raises SerpApiError on any failure ("no results" is
    not a failure)."""
    try:
        resp = client.get(SERPAPI_URL, params={**params, "api_key": api_key})
    except httpx.HTTPError as exc:  # its message can carry the URL (and key), so keep only the type
        raise SerpApiError(type(exc).__name__) from None
    try:
        data = resp.json()
    except ValueError:
        raise SerpApiError(f"invalid JSON (HTTP {resp.status_code})") from None
    if not isinstance(data, dict):
        raise SerpApiError(f"unexpected response (HTTP {resp.status_code})")
    error = str(data.get("error") or "")
    if resp.status_code != 200 or (error and NO_RESULTS_ERROR not in error):
        raise SerpApiError(f"HTTP {resp.status_code}: {clean_text(error, 120)}")
    return data


def _handle_query(kind: str, handle: str) -> dict[str, Any]:
    return {"engine": "google", "q": f'site:{SITES[kind]} "{handle}"', "num": 5}


def search_handle(client: httpx.Client, api_key: str, kind: str, handle: str) -> str | None:
    """Notes for one handle, or None when nothing usable was found. Raises SerpApiError."""
    return distill(kind, handle, serpapi_search(client, api_key, _handle_query(kind, handle)))


def _demo_social(kind: str, handle: str) -> dict[str, Any]:
    name = handle.lstrip("@")
    return {
        "kind": kind,
        "handle": handle,
        "display_name": name,
        "bio": "Builder · UT Austin · open to HackTX squads",
        "profile_url": f"https://{SITES.get(kind, kind + '.com')}/{name}",
        "notes": "Public profile signals: React, campus tools, climate apps.",
    }


def social_preview(kind: str, handle: str) -> dict[str, Any]:
    """GET /api/enrichment/social: the public profile page SerpAPI finds for a handle,
    {"source", "engine": "google", "result": {kind, handle, display_name, bio, profile_url, notes}}.
    Uses the same site-restricted query as the profile lookup. Unsearchable kinds, a missing
    SERPAPI_API_KEY or a failed call return demo data with source "demo_fallback"."""
    settings = get_settings()
    normalized = normalize_handle(kind, handle)
    fallback = {"source": "demo_fallback", "engine": "google", "result": _demo_social(kind, handle)}
    if normalized is None or not settings.serpapi_configured:
        return fallback
    try:
        with httpx.Client(timeout=settings.serpapi_timeout_s) as client:
            data = serpapi_search(client, settings.serpapi_api_key, _handle_query(kind, normalized))
    except SerpApiError as exc:
        log.warning("SerpAPI social preview failed: %s", exc)
        return fallback
    page: dict[str, Any] = {}
    for item in data.get("organic_results") or []:
        if not isinstance(item, dict):
            continue
        link = urlsplit(str(item.get("link") or ""))
        host = (link.hostname or "").lower()
        if (host == SITES[kind] or host.endswith("." + SITES[kind])) and (
            _profile_segment(kind, link.path).lower() == normalized
        ):
            page = item
            break
    snippet = clean_text(page.get("snippet"), 300) or None
    return {
        "source": "serpapi",
        "engine": "google",
        "result": {
            "kind": kind,
            "handle": handle,
            "display_name": clean_text(page.get("title"), 120) or normalized,
            "bio": snippet or "",
            "profile_url": page.get("link"),
            "notes": snippet,
        },
    }


def _is_fresh(row: SocialLookup | None, ttl: timedelta) -> bool:
    if row is None:
        return False
    max_age = ttl if row.status == "ok" else min(ttl, FAILED_RETRY)
    return utcnow() - row.fetched_at < max_age


def _cached(db: Session, handles: list[Handle]) -> dict[Handle, SocialLookup]:
    if not handles:
        return {}
    rows = db.exec(
        select(SocialLookup).where(tuple_(SocialLookup.kind, SocialLookup.handle).in_(handles))
    ).all()
    return {(r.kind, r.handle): r for r in rows}


def _store(db: Session, kind: str, handle: str, status: str, notes: str | None) -> None:
    """Upsert one lookup. A failure never overwrites an earlier good result."""
    now = utcnow()
    stmt = pg_insert(SocialLookup).values(
        id=new_id("soc"), kind=kind, handle=handle, status=status, notes=notes, fetched_at=now
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_social_lookups_kind_handle",
        set_={"status": status, "notes": notes, "fetched_at": now},
        where=(SocialLookup.status == "failed") if status == "failed" else None,
    )
    db.execute(stmt)


def _fetch(db: Session, handles: list[Handle], settings: Settings) -> None:
    """Query SerpAPI for each handle and cache the outcome (committed)."""
    with httpx.Client(timeout=settings.serpapi_timeout_s) as client:
        for kind, handle in handles:
            try:
                notes = search_handle(client, settings.serpapi_api_key, kind, handle)
                status = "ok"
            except SerpApiError as exc:
                log.warning("SerpAPI lookup of a %s handle failed: %s", kind, exc)
                notes, status = None, "failed"
            _store(db, kind, handle, status, notes)
            db.commit()


def combined_notes(handles: list[Handle], cache: dict[Handle, SocialLookup]) -> str | None:
    """The profile's social_notes: the cached notes of each handle, in order, size-capped.
    Redacted again because rows cached before distill() redacted handles may still hold them."""
    parts = [
        redact_handle(cache[h].notes, h[1])
        for h in handles if h in cache and cache[h].status == "ok" and cache[h].notes
    ]
    parts = [p for p in parts if p]
    if not parts:
        return None
    return clean_text(" | ".join(parts), MAX_NOTES_CHARS)


def lookup_socials(user_id: str, submitted: list[dict[str, Any]]) -> None:
    """Background task: refresh the user's social_notes after they submitted these handles.

    The profile's current socials (which include the submitted ones) are looked up, so the notes
    always describe the handles the profile has now. When nothing submitted can be searched but a
    site's handle was replaced (by an unsearchable value), the notes are still recomputed from the
    cache so they stop describing the old handle. Opens its own DB session and never raises.
    """
    try:
        settings = get_settings()
        fetch = bool(searchable_handles(submitted))
        if fetch and not settings.serpapi_configured:
            log.info("SERPAPI_API_KEY is not configured; skipping the social lookup")
            fetch = False
        replaced = any(
            s.get("kind") in SITES and normalize_handle(str(s["kind"]), str(s.get("value", ""))) is None
            for s in submitted
        )
        if not fetch and not replaced:
            return
        ttl = timedelta(hours=settings.social_lookup_ttl_hours)
        with Session(get_engine()) as db:
            if fetch:
                profile = db.exec(select(Profile).where(Profile.user_id == user_id)).first()
                if profile is None:
                    return
                handles = searchable_handles(profile.socials)
                cache = _cached(db, handles)
                stale = [h for h in handles if not _is_fresh(cache.get(h), ttl)]
                db.rollback()  # no transaction held open during the HTTP calls
                if stale:
                    _fetch(db, stale, settings)

            # Under the profile lock, from the socials it has now (a later join may have changed them).
            profile = db.exec(
                select(Profile).where(Profile.user_id == user_id).with_for_update()
                .execution_options(populate_existing=True)
            ).first()
            if profile is None:
                return
            current = searchable_handles(profile.socials)
            notes = combined_notes(current, _cached(db, current))
            if notes == profile.social_notes:
                db.rollback()
                return
            profile.social_notes = notes
            profile.updated_at = utcnow()
            db.add(profile)
            db.commit()
            refresh_member_texts(db, user_id)
    except Exception:
        log.exception("social lookup for user %s failed", user_id)
