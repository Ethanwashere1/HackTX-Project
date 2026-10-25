"""Person profiles and per-event match text, plus hooks for the later pipeline steps.

A user has one Profile (socials, social_notes, interview summary, AI overview) shared across
events. Each EventMember holds that event's answers and fields and the combined `profile_text`,
which is what gets embedded and sent to the agents' rerank. Whenever the profile or a membership
changes, rebuild the affected texts (refresh_member_texts) so every event sees the change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from app.ids import new_id
from app.models import Event, EventMember, Profile, Question, User
from app.models.base import utcnow
from app.services.events import event_questions

log = logging.getLogger(__name__)


def get_or_create_profile(db: Session, user_id: str, *, lock: bool = False) -> Profile:
    """The user's profile, created empty if missing (not committed). Safe under concurrent calls.

    `lock=True` takes a row lock (SELECT ... FOR UPDATE) for read-modify-write updates.
    """
    db.execute(
        pg_insert(Profile)
        .values(id=new_id("prf"), user_id=user_id, traits={}, transcript=[], socials=[],
                updated_at=utcnow())
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    query = select(Profile).where(Profile.user_id == user_id)
    if lock:
        query = query.with_for_update()
    return db.exec(query.execution_options(populate_existing=True)).one()


def merge_socials(
    current: list[dict[str, Any]], submitted: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Submitted handles replace the existing handles of the same kind; other kinds are kept."""
    kinds = {s["kind"] for s in submitted}
    return [s for s in current if s["kind"] not in kinds] + [
        {"kind": s["kind"], "value": s["value"]} for s in submitted
    ]


def display_summary(profile: Profile | None) -> str | None:
    """Prefer AI overview over interview summary (CONTRACT §1 / §4 / team page)."""
    if profile is None:
        return None
    return profile.overview or profile.summary


def topic_signals(traits: dict[str, Any] | None) -> list[str]:
    """Split traits['topics'] into a list for the enriched /recommend payload."""
    if not traits:
        return []
    raw = traits.get("topics")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def group_need(traits: dict[str, Any] | None) -> str | None:
    if not traits:
        return None
    value = traits.get("group_need")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def build_member_text(
    event: Event, questions: list[Question], member: EventMember, profile: Profile | None
) -> str:
    """Plain-text match profile for one event membership. Deterministic for a given input.

    The event's fields and answers, then the person profile: socials, public info, overview,
    interview summary and traits (CONTRACT §4 matching signals).
    """
    lines = [f"Event: {event.name} ({event.type}, {event.tone})"]
    for key, value in (member.fields or {}).items():
        lines.append(f"{key.replace('_', ' ').capitalize()}: {_fmt(value)}")
    answers = member.answers or {}
    for q in questions:
        if q.id in answers:
            lines.append(f"Q: {q.text}\nA: {_fmt(answers[q.id])}")
    if profile is not None:
        if profile.socials:
            lines.append("Socials: " + ", ".join(f"{s['kind']} {s['value']}" for s in profile.socials))
        if profile.social_notes:
            lines.append(f"Public info: {profile.social_notes}")
        if profile.overview:
            lines.append(f"Overview: {profile.overview}")
        if profile.summary:
            lines.append(f"Interview summary: {profile.summary}")
        if profile.traits:
            lines.append(
                "Traits: " + ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(profile.traits.items()))
            )
    return "\n".join(lines)


def rebuild_member_texts(
    db: Session, user_id: str, event_ids: list[str] | None = None
) -> list[str]:
    """Rebuild `profile_text` for the user's memberships (all, or in `event_ids`) without
    committing or calling the hook. Returns the affected event_member ids."""
    if event_ids is not None and not event_ids:
        return []
    query = select(EventMember).where(EventMember.user_id == user_id)
    if event_ids is not None:
        query = query.where(EventMember.event_id.in_(event_ids))
    members = list(db.exec(query.order_by(EventMember.joined_at, EventMember.id)).all())
    if not members:
        return []
    profile = db.exec(select(Profile).where(Profile.user_id == user_id)).first()
    for member in members:
        event = db.get(Event, member.event_id)
        member.profile_text = build_member_text(event, event_questions(db, event.id), member, profile)
        db.add(member)
    return [m.id for m in members]


def refresh_member_texts(
    db: Session, user_id: str, event_ids: list[str] | None = None
) -> list[str]:
    """Rebuild and commit `profile_text` for the user's memberships (all, or in `event_ids`), then
    call on_member_text_changed. Returns the affected event_member ids.

    Call it after changing the user's Profile (interview summary, social notes, overview). The hook
    runs inline here, so from a request handler prefer calling this in a background task.
    """
    ids = rebuild_member_texts(db, user_id, event_ids)
    db.commit()
    if ids:
        run_hook(on_member_text_changed, ids)
    return ids


def on_member_text_changed(member_ids: list[str]) -> None:
    """Hook: these event members' `profile_text` changed and is committed.

    Runs as a background task after the response, so it must open its own DB session
    (`with Session(app.db.get_engine()) as db:`) and must never raise into the caller.

    TODO(embeddings builder): embed each member's profile_text with Gemini, store it in
    `event_members.embedding` + `embedded_at` (pgvector) and sync to Snowflake
    (`snowflake_synced_at`). Skip while not configured; leave the embedding null on failure.
    """
    log.debug("member texts changed: %s; embedding not implemented yet", member_ids)


def schedule_social_lookup(user_id: str, socials: list[dict[str, Any]]) -> None:
    """Hook: the user submitted these social handles ([{kind, value}]).

    Runs as a background task after the response, so it must open its own DB session and must
    never raise into the caller.

    TODO(SerpAPI builder): look the handles up (cached in social_lookups), write
    `profiles.social_notes`, then call schedule_overview_refresh(user_id) (which re-embeds).
    Skip on failure or while SERPAPI_API_KEY is not configured.
    """
    log.debug("user %s: SerpAPI lookup of %d handles not implemented yet", user_id, len(socials))


def _latest_membership(
    db: Session, user_id: str, event_id: str | None
) -> tuple[Event | None, EventMember | None]:
    if event_id is not None:
        event = db.get(Event, event_id)
        member = db.exec(
            select(EventMember).where(
                EventMember.event_id == event_id, EventMember.user_id == user_id
            )
        ).first()
        return event, member
    member = db.exec(
        select(EventMember)
        .where(EventMember.user_id == user_id)
        .order_by(EventMember.joined_at.desc(), EventMember.id.desc())
    ).first()
    if member is None:
        return None, None
    return db.get(Event, member.event_id), member


def overview_request_body(
    db: Session, user: User, profile: Profile, *, event_id: str | None = None
) -> dict[str, Any]:
    """Build the CONTRACT §8 POST /profile-overview request body."""
    event, member = _latest_membership(db, user.id, event_id)
    body: dict[str, Any] = {
        "user": {"user_id": user.id, "name": user.name},
        "answers": dict(member.answers) if member and member.answers else {},
        "fields": dict(member.fields) if member and member.fields else {},
        "social_notes": profile.social_notes,
        "interview_summary": profile.summary,
        "interview_traits": dict(profile.traits) if profile.traits else {},
    }
    if event is not None:
        body["event"] = {
            "event_id": event.id,
            "name": event.name,
            "type": event.type,
            "tone": event.tone,
        }
    return body


def apply_overview_result(profile: Profile, result: dict[str, Any]) -> None:
    """Persist overview and merge returned traits onto the profile (not committed)."""
    profile.overview = result["overview"]
    incoming = result.get("traits") or {}
    if isinstance(incoming, dict) and incoming:
        profile.traits = {**(profile.traits or {}), **incoming}
    profile.updated_at = utcnow()


def regenerate_overview(db: Session, user_id: str, *, event_id: str | None = None) -> bool:
    """Call agents /profile-overview, persist on success, refresh member texts. Returns True if saved.

    Opens no sessions of its own; caller provides `db`. Failures leave the prior overview alone.
    """
    from app.services import agents as agents_client

    user = db.get(User, user_id)
    if user is None:
        return False
    profile = get_or_create_profile(db, user_id, lock=True)
    body = overview_request_body(db, user, profile, event_id=event_id)
    result = agents_client.fetch_profile_overview(body)
    if result is None:
        return False
    apply_overview_result(profile, result)
    db.add(profile)
    db.commit()
    refresh_member_texts(db, user_id)
    return True


def schedule_overview_refresh(user_id: str, event_id: str | None = None) -> None:
    """Background hook: regenerate the shared profile overview, then re-embed via refresh.

    Must never raise into the caller. Opens its own DB session.
    """
    from app import db as dbmod

    try:
        with Session(dbmod.get_engine()) as db:
            ok = regenerate_overview(db, user_id, event_id=event_id)
            if ok:
                log.info("overview refreshed for user %s", user_id)
            else:
                log.info("overview unchanged for user %s (agents unavailable or failed)", user_id)
    except Exception:
        log.exception("schedule_overview_refresh failed for user %s", user_id)


def on_interview_summary_saved(user_id: str, event_id: str | None = None) -> None:
    """Call after interview summary/traits are committed: regenerate overview + re-embed."""
    schedule_overview_refresh(user_id, event_id)


def on_social_notes_updated(user_id: str) -> None:
    """Call after SerpAPI (or similar) writes profiles.social_notes: regenerate overview + re-embed."""
    schedule_overview_refresh(user_id)


def run_hook(hook: Callable[..., None], *args: Any) -> None:
    """Run a background hook, logging instead of raising, so a failure never breaks a request."""
    try:
        hook(*args)
    except Exception:
        log.exception("background hook %s failed", getattr(hook, "__name__", hook))
