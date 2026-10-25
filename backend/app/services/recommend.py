"""Helpers for building the enriched agents POST /recommend payload (CONTRACT §4 / §8).

The GET /api/events/{id}/recommendations endpoint (similarity + exclusions) is a separate
task; this module is the agents-facing enrichment layer that endpoint should call.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.models import Event, EventMember, Profile, User
from app.services import agents as agents_client
from app.services.profiles import display_summary, group_need, topic_signals


def person_summary(db: Session, user_id: str) -> str | None:
    """people[].summary: overview when present, else interview summary."""
    profile = db.exec(select(Profile).where(Profile.user_id == user_id)).first()
    return display_summary(profile)


def enrich_viewer(db: Session, event: Event, viewer_id: str) -> dict[str, Any]:
    """Viewer object for POST /recommend, including optional traits / topic_signals / group_need."""
    member = db.exec(
        select(EventMember).where(EventMember.event_id == event.id, EventMember.user_id == viewer_id)
    ).first()
    profile = db.exec(select(Profile).where(Profile.user_id == viewer_id)).first()
    traits = dict(profile.traits) if profile and profile.traits else {}
    payload: dict[str, Any] = {
        "user_id": viewer_id,
        "profile_text": member.profile_text if member else "",
    }
    if traits:
        payload["traits"] = traits
    signals = topic_signals(traits)
    if signals:
        payload["topic_signals"] = signals
    need = group_need(traits)
    if need is not None:
        payload["group_need"] = need
    return payload


def enrich_user_candidate(
    db: Session, event_id: str, user_id: str, *, similarity: float
) -> dict[str, Any]:
    """One user candidate for POST /recommend."""
    member = db.exec(
        select(EventMember).where(EventMember.event_id == event_id, EventMember.user_id == user_id)
    ).first()
    profile = db.exec(select(Profile).where(Profile.user_id == user_id)).first()
    traits = dict(profile.traits) if profile and profile.traits else {}
    payload: dict[str, Any] = {
        "candidate_type": "user",
        "id": user_id,
        "profile_text": member.profile_text if member else "",
        "similarity": similarity,
    }
    if traits:
        payload["traits"] = traits
    signals = topic_signals(traits)
    if signals:
        payload["topic_signals"] = signals
    need = group_need(traits)
    if need is not None:
        payload["group_need"] = need
    return payload


def enrich_group_candidate(
    *,
    group_id: str,
    profile_text: str,
    similarity: float,
    traits: dict[str, Any] | None = None,
    topic_signals_list: list[str] | None = None,
    group_need_value: str | None = None,
) -> dict[str, Any]:
    """One group candidate for POST /recommend (traits often aggregated by the caller)."""
    traits = traits or {}
    payload: dict[str, Any] = {
        "candidate_type": "group",
        "id": group_id,
        "profile_text": profile_text,
        "similarity": similarity,
        "traits": traits,
    }
    signals = topic_signals_list if topic_signals_list is not None else topic_signals(traits)
    if signals:
        payload["topic_signals"] = signals
    need = group_need_value if group_need_value is not None else group_need(traits)
    payload["group_need"] = need
    return payload


def recommend_request_body(
    event: Event,
    viewer: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Full POST /recommend body."""
    return {
        "event": {
            "event_id": event.id,
            "type": event.type,
            "tone": event.tone,
            "description": event.description or "",
        },
        "viewer": viewer,
        "candidates": candidates,
        "limit": limit,
    }


def rerank_with_agents(
    event: Event,
    viewer: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]] | None:
    """Call agents /recommend with the enriched payload. None => use similarity order."""
    if not candidates:
        return []
    body = recommend_request_body(event, viewer, candidates, limit=limit)
    return agents_client.recommend(body)


def people_card(db: Session, user_id: str, *, score: float, reason: str | None) -> dict[str, Any]:
    """One people[] entry for the GET recommendations response."""
    user = db.get(User, user_id)
    return {
        "user_id": user_id,
        "name": user.name if user else None,
        "summary": person_summary(db, user_id),
        "score": score,
        "reason": reason,
    }
