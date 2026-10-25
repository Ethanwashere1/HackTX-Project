"""HTTP client for the Gemini agents service (CONTRACT section 8).

Every call sends X-Internal-Key, uses a hard timeout, and never raises into a request
handler for optional paths (overview). QuizGen raises AppError so the proxy can return 502.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings, is_placeholder
from app.errors import AppError

log = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    settings = get_settings()
    key = settings.internal_api_key if settings.internal_key_configured else ""
    return {"X-Internal-Key": key, "Content-Type": "application/json"}


def _base_url() -> str:
    return get_settings().agents_url.rstrip("/")


def agents_configured() -> bool:
    """Agents URL and internal key are both set (not placeholders)."""
    settings = get_settings()
    return settings.internal_key_configured and not is_placeholder(settings.agents_url)


def fetch_profile_overview(body: dict[str, Any], *, timeout_s: float | None = None) -> dict[str, Any] | None:
    """POST /profile-overview. Returns {overview, traits} or None on any failure.

    Never raises: join / interview / social updates must succeed without agents.
    """
    settings = get_settings()
    if timeout_s is None:
        timeout_s = settings.agents_overview_timeout_s
    if not agents_configured():
        log.info("agents not configured; skipping profile-overview")
        return None
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(f"{_base_url()}/profile-overview", json=body, headers=_headers())
        if resp.status_code != 200:
            log.warning("profile-overview returned %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        overview = data.get("overview")
        if not isinstance(overview, str) or not overview.strip():
            log.warning("profile-overview missing overview string")
            return None
        traits = data.get("traits") if isinstance(data.get("traits"), dict) else {}
        return {"overview": overview.strip(), "traits": {str(k): v for k, v in traits.items()}}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        log.warning("profile-overview failed: %s", exc)
        return None


def generate_questions(body: dict[str, Any], *, timeout_s: float | None = None) -> list[dict[str, Any]]:
    """POST /generate-questions. Returns the questions list, or raises AppError agents_unavailable."""
    settings = get_settings()
    if timeout_s is None:
        timeout_s = settings.agents_questions_timeout_s
    if not agents_configured():
        raise AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable")
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(f"{_base_url()}/generate-questions", json=body, headers=_headers())
    except httpx.HTTPError as exc:
        log.warning("generate-questions failed: %s", exc)
        raise AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable") from exc
    if resp.status_code != 200:
        log.warning("generate-questions returned %s: %s", resp.status_code, resp.text[:200])
        raise AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable")
    try:
        data = resp.json()
    except ValueError as exc:
        raise AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable") from exc
    questions = data.get("questions")
    if not isinstance(questions, list):
        raise AppError(502, "agents_unavailable", "Question suggestions are temporarily unavailable")
    return questions


def recommend(
    body: dict[str, Any], *, timeout_s: float | None = None
) -> list[dict[str, Any]] | None:
    """POST /recommend. Returns results list, or None so the caller can fall back to similarity.

    Optional path: never raises into the recommendations handler.
    """
    settings = get_settings()
    if timeout_s is None:
        timeout_s = settings.agents_timeout_s
    if not agents_configured():
        log.info("agents not configured; skipping recommend rerank")
        return None
    try:
        with httpx.Client(timeout=timeout_s) as client:
            resp = client.post(f"{_base_url()}/recommend", json=body, headers=_headers())
        if resp.status_code != 200:
            log.warning("recommend returned %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        results = data.get("results")
        if not isinstance(results, list):
            return None
        return results
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        log.warning("recommend failed: %s", exc)
        return None
