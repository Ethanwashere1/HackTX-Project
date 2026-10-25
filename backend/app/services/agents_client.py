"""Client for the Gemini agents service (contract section 8): POST /recommend."""

import logging
import math
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

MAX_REASON_CHARS = 300  # a reason is a sentence or two on a card; longer output is cut


def _post(url: str, **kwargs) -> httpx.Response:
    return httpx.post(url, **kwargs)


def _clip(text: str) -> str:
    if len(text) <= MAX_REASON_CHARS:
        return text
    return text[:MAX_REASON_CHARS - 1].rstrip() + "…"


def rerank(
    event: dict[str, Any], viewer: dict[str, Any], candidates: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]] | None:
    """The agent's reranked picks: [{candidate_type, id, score, reason}], best first.

    Keeps only results whose (candidate_type, id) was among `candidates`, once each, with each
    reason cut to MAX_REASON_CHARS. Returns None when the agents service is not configured,
    fails, times out or returns nothing usable; the caller then falls back to the similarity order.
    """
    settings = get_settings()
    if not candidates:
        return None
    if not settings.internal_key_configured:
        log.info("INTERNAL_API_KEY not configured; skipping the agents rerank")
        return None
    body = {"event": event, "viewer": viewer, "candidates": candidates, "limit": limit}
    try:
        resp = _post(
            f"{settings.agents_url.rstrip('/')}/recommend",
            json=body,
            headers={"X-Internal-Key": settings.internal_api_key},
            timeout=settings.agents_timeout_s,
        )
    except httpx.HTTPError as exc:
        log.warning("Agents /recommend failed: %s", exc.__class__.__name__)
        return None
    if resp.status_code != 200:
        log.warning("Agents /recommend returned HTTP %d", resp.status_code)
        return None
    try:
        results = resp.json()["results"]
    except (ValueError, KeyError, TypeError):
        log.warning("Agents /recommend returned an invalid body")
        return None
    if not isinstance(results, list):
        log.warning("Agents /recommend returned an invalid body")
        return None

    known = {(c["candidate_type"], c["id"]) for c in candidates}
    picked: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        key = (item.get("candidate_type"), item.get("id"))
        if key not in known or key in seen:
            continue
        seen.add(key)
        score = item.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            score = None
        reason = item.get("reason")
        reason = _clip(reason.strip()) or None if isinstance(reason, str) else None
        picked.append({"candidate_type": key[0], "id": key[1], "score": score, "reason": reason})
    if not picked:
        log.warning("Agents /recommend returned no known candidates")
        return None
    return picked
