"""Client for the Gemini agents service (contract section 8): POST /recommend,
POST /profile-overview and POST /generate-questions.

Every call sends X-Internal-Key with a hard timeout. The optional paths (the recommend rerank and
the profile overview) return None on any failure so the caller falls back; question generation
raises AppError 502 `agents_unavailable` for the proxy endpoint to return.
"""

import logging
import math
from typing import Any

import httpx

from app.config import get_settings, is_placeholder
from app.errors import AppError

log = logging.getLogger(__name__)

MAX_REASON_CHARS = 300  # a reason is a sentence or two on a card; longer output is cut
MAX_OVERVIEW_CHARS = 1000


def _post(url: str, *, json: dict[str, Any], headers: dict[str, str], timeout: float) -> httpx.Response:
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, json=json, headers=headers)


def agents_configured() -> bool:
    """AGENTS_URL and INTERNAL_API_KEY are both set (not placeholders)."""
    settings = get_settings()
    return settings.internal_key_configured and not is_placeholder(settings.agents_url)


def _call(path: str, body: dict[str, Any], timeout: float) -> httpx.Response:
    settings = get_settings()
    return _post(
        f"{settings.agents_url.rstrip('/')}{path}",
        json=body,
        headers={"X-Internal-Key": settings.internal_api_key},
        timeout=timeout,
    )


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
    if not agents_configured():
        log.info("Agents service not configured; skipping the agents rerank")
        return None
    body = {"event": event, "viewer": viewer, "candidates": candidates, "limit": limit}
    try:
        resp = _call("/recommend", body, settings.agents_timeout_s)
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


def fetch_profile_overview(body: dict[str, Any]) -> dict[str, Any] | None:
    """POST /profile-overview: {"overview": str, "traits": dict}, or None on any failure (not
    configured, error, timeout, invalid body). Never raises: joins and interviews succeed without it."""
    settings = get_settings()
    if not agents_configured():
        log.info("Agents service not configured; skipping the profile overview")
        return None
    try:
        resp = _call("/profile-overview", body, settings.agents_overview_timeout_s)
    except httpx.HTTPError as exc:
        log.warning("Agents /profile-overview failed: %s", exc.__class__.__name__)
        return None
    if resp.status_code != 200:
        log.warning("Agents /profile-overview returned HTTP %d", resp.status_code)
        return None
    try:
        data = resp.json()
        overview = data.get("overview")
        traits = data.get("traits")
    except (ValueError, AttributeError):
        log.warning("Agents /profile-overview returned an invalid body")
        return None
    if not isinstance(overview, str) or not overview.strip():
        log.warning("Agents /profile-overview returned no overview")
        return None
    traits = traits if isinstance(traits, dict) else {}
    # One line: it becomes the "Overview:" line of every match profile_text.
    overview = " ".join(overview.split())[:MAX_OVERVIEW_CHARS]
    return {"overview": overview, "traits": {str(k): v for k, v in traits.items()}}


def _questions_unavailable() -> AppError:
    return AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable")


def generate_questions(body: dict[str, Any]) -> list[Any]:
    """POST /generate-questions: the raw `questions` list. Raises AppError 502 agents_unavailable
    when the service is not configured, fails, times out or returns an invalid body."""
    settings = get_settings()
    if not agents_configured():
        raise _questions_unavailable()
    try:
        resp = _call("/generate-questions", body, settings.agents_questions_timeout_s)
    except httpx.HTTPError as exc:
        log.warning("Agents /generate-questions failed: %s", exc.__class__.__name__)
        raise _questions_unavailable() from None
    if resp.status_code != 200:
        log.warning("Agents /generate-questions returned HTTP %d", resp.status_code)
        raise _questions_unavailable()
    try:
        questions = resp.json().get("questions")
    except (ValueError, AttributeError):
        questions = None
    if not isinstance(questions, list):
        log.warning("Agents /generate-questions returned an invalid body")
        raise _questions_unavailable()
    return questions
