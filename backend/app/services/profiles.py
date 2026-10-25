"""Matching profiles: the text that gets embedded, plus hooks for the later pipeline steps."""

import logging
from typing import Any

from app.models import Event, Profile, Question

log = logging.getLogger(__name__)


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def build_profile_text(
    event: Event,
    questions: list[Question],
    answers: dict[str, Any],
    fields: dict[str, Any],
    socials: list[dict[str, str]],
    *,
    social_notes: str | None = None,
    summary: str | None = None,
) -> str:
    """Plain-text profile for embeddings and the agents' rerank. Deterministic for a given input."""
    lines = [f"Event: {event.name} ({event.type}, {event.tone})"]
    for key, value in fields.items():
        lines.append(f"{key.replace('_', ' ').capitalize()}: {_fmt(value)}")
    for q in questions:
        if q.id in answers:
            lines.append(f"Q: {q.text}\nA: {_fmt(answers[q.id])}")
    if socials:
        lines.append("Socials: " + ", ".join(f"{s['kind']} {s['value']}" for s in socials))
    if social_notes:
        lines.append(f"Public info: {social_notes}")
    if summary:
        lines.append(f"Interview summary: {summary}")
    return "\n".join(lines)


def on_profile_saved(profile: Profile) -> None:
    """Hook, called after a profile's text is committed.

    TODO(M1 embeddings task): embed `profile.profile_text` with Gemini, store it in
    `profile.embedding` (pgvector) and sync it to Snowflake. Until then the embedding stays null.
    """
    log.debug("profile %s saved; embedding not implemented yet", profile.id)


def schedule_social_lookup(profile: Profile, socials: list[dict[str, str]]) -> None:
    """Hook, called after a join with social handles.

    TODO(M3 SerpAPI task): look the handles up asynchronously (never blocking the join), write
    `profile.social_notes`, rebuild `profile_text` and call on_profile_saved(). Skip on failure.
    """
    if socials:
        log.debug("profile %s: SerpAPI lookup not implemented yet", profile.id)
