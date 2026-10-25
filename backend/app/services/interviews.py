"""Contract section 8: the interview token lifecycle and what the agents service reads and writes.

An InterviewToken (stored hashed) goes through three steps:
1. POST /api/events/{id}/interview issues it, valid for 10 minutes.
2. GET .../config claims it (sets used_at). It must be unexpired and unclaimed, so one token opens
   exactly one interview.
3. POST .../summary needs a claimed token, within SUMMARY_WINDOW of the claim, and consumes it
   (the row is deleted), so each interview saves its summary at most once.

The interview may outlast the 10-minute issue window, so the summary deadline counts from the claim.
"""

from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from app.auth.sessions import hash_token
from app.errors import AppError
from app.models import Event, InterviewToken, Profile, User
from app.models.base import utcnow
from app.services.events import event_questions, get_membership, is_approved_org_member
from app.services.profiles import get_or_create_profile, rebuild_member_texts

MAX_MINUTES = 5
# The agents service ends the interview at max_minutes, then summarizes (up to ~45 s) and posts.
SUMMARY_WINDOW = timedelta(minutes=MAX_MINUTES + 5)
MAX_TOKEN_LENGTH = 100


def _invalid(message: str) -> AppError:
    return AppError(401, "unauthenticated", message)


def _lock_token(db: Session, raw_token: str) -> InterviewToken:
    """The token row, locked (SELECT ... FOR UPDATE) so concurrent calls see each other's claim."""
    if not raw_token or len(raw_token) > MAX_TOKEN_LENGTH:
        raise _invalid("Unknown interview token")
    token = db.exec(
        select(InterviewToken)
        .where(InterviewToken.token_hash == hash_token(raw_token))
        .with_for_update()
    ).first()
    if token is None:
        raise _invalid("Unknown or already used interview token")
    return token


def _require_event_member(db: Session, token: InterviewToken) -> Event:
    """403 unless the user is still in the event (and, for org events, an approved org member)."""
    event = db.get(Event, token.event_id)
    if (
        event is None
        or get_membership(db, event.id, token.user_id) is None
        or (event.org_id is not None and not is_approved_org_member(db, event.org_id, token.user_id))
    ):
        raise AppError(403, "forbidden", "The user is no longer a member of this event")
    return event


def claim_for_config(db: Session, raw_token: str) -> dict:
    """Claim the token and return the interview config (contract section 8). Commits."""
    token = _lock_token(db, raw_token)
    now = utcnow()
    if token.used_at is not None:
        raise _invalid("Interview token already used")
    if token.expires_at <= now:
        raise _invalid("Interview token expired")
    event = _require_event_member(db, token)
    user = db.get(User, token.user_id)
    member = get_membership(db, event.id, user.id)
    profile = db.exec(select(Profile).where(Profile.user_id == user.id)).first()
    config = {
        "user": {"user_id": user.id, "name": user.name},
        "event": {
            "event_id": event.id,
            "name": event.name,
            "type": event.type,
            "tone": event.tone,
            "description": event.description,
        },
        "questions": [{"question_id": q.id, "text": q.text} for q in event_questions(db, event.id)],
        "profile_so_far": {
            "answers": member.answers or {},
            "fields": member.fields or {},
            "social_notes": profile.social_notes if profile else None,
        },
        "max_minutes": MAX_MINUTES,
    }
    token.used_at = now
    db.add(token)
    db.commit()
    return config


def save_summary(
    db: Session,
    raw_token: str,
    *,
    summary: str,
    traits: dict[str, Any],
    transcript: list[dict[str, Any]],
    input_mode: str | None,
) -> tuple[str, str, list[str]]:
    """Store the interview on the user's profile, consume the token and rebuild the user's event
    match texts. Commits. Returns (user_id, event_id, the affected event_member ids for
    on_member_text_changed)."""
    token = _lock_token(db, raw_token)
    if token.used_at is None:
        raise _invalid("This interview token was never used to start an interview")
    if utcnow() > token.used_at + SUMMARY_WINDOW:
        raise _invalid("Interview token expired")
    _require_event_member(db, token)
    user_id, event_id = token.user_id, token.event_id

    profile = get_or_create_profile(db, user_id, lock=True)
    profile.summary = summary
    profile.traits = traits
    profile.transcript = transcript
    profile.interview_input_mode = input_mode
    profile.updated_at = utcnow()
    db.add(profile)
    db.delete(token)
    db.flush()
    # The summary is part of every event's match text, not just the interviewed event's.
    member_ids = rebuild_member_texts(db, user_id)
    db.commit()
    return user_id, event_id, member_ids
