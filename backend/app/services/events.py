"""Event access rules, join validation and the GET /api/events/{id} body."""

import math
from typing import Any

from sqlmodel import Session, func, select

from app.config import get_settings
from app.errors import AppError
from app.models import Event, EventMember, Group, GroupMember, OrgMember, Question, User
from app.models.base import iso

MAX_TEXT_ANSWER = 2000
MAX_FIELD_TEXT = 500
MAX_FIELD_LIST = 50
MAX_FIELD_ITEM = 100


def is_approved_org_member(db: Session, org_id: str, user_id: str) -> bool:
    return (
        db.exec(
            select(OrgMember.id).where(
                OrgMember.org_id == org_id,
                OrgMember.user_id == user_id,
                OrgMember.status == "approved",
            )
        ).first()
        is not None
    )


def require_org_member(db: Session, org_id: str, user: User) -> None:
    """403 `not_org_member` unless the user is an approved member (also for unknown orgs)."""
    if not is_approved_org_member(db, org_id, user.id):
        raise AppError(403, "not_org_member", "Only approved members of this org can do that")


def get_visible_event(db: Session, event_id: str, user: User) -> Event:
    """The event, if the user may see it: org events need approved org membership; events without
    an org are unlisted and reachable by link by any signed-in user."""
    event = db.get(Event, event_id)
    if event is None:
        raise AppError(404, "not_found", "Event not found")
    if event.org_id is not None:
        require_org_member(db, event.org_id, user)
    return event


def get_membership(db: Session, event_id: str, user_id: str) -> EventMember | None:
    return db.exec(
        select(EventMember).where(EventMember.event_id == event_id, EventMember.user_id == user_id)
    ).first()


def event_questions(db: Session, event_id: str) -> list[Question]:
    return list(
        db.exec(
            select(Question)
            .where(Question.event_id == event_id)
            .order_by(Question.position, Question.id)
        ).all()
    )


def share_url(event_id: str) -> str:
    return f"{get_settings().frontend_origin.rstrip('/')}/events/{event_id}"


def event_payload(db: Session, event: Event, user: User) -> dict:
    host = db.get(User, event.host_id)
    member = get_membership(db, event.id, user.id)
    my_membership = None
    if member is not None:
        group_id = db.exec(
            select(GroupMember.group_id)
            .where(GroupMember.event_id == event.id, GroupMember.user_id == user.id)
            .order_by(GroupMember.joined_at, GroupMember.id)
        ).first()
        my_membership = {"joined_at": iso(member.joined_at), "group_id": group_id}
    member_count = db.exec(
        select(func.count()).select_from(EventMember).where(EventMember.event_id == event.id)
    ).one()
    groups_formed = db.exec(
        select(func.count()).select_from(Group).where(Group.event_id == event.id)
    ).one()
    return {
        "event_id": event.id,
        "org_id": event.org_id,
        "name": event.name,
        "description": event.description,
        "type": event.type,
        "tone": event.tone,
        "group_count": event.group_count,
        "min_size": event.min_size,
        "max_size": event.max_size,
        "max_groups_per_user": event.max_groups_per_user,
        "required_fields": event.required_fields,
        "questions": [
            {
                "question_id": q.id,
                "text": q.text,
                "kind": q.kind,
                "options": q.options,
                "required": q.required,
            }
            for q in event_questions(db, event.id)
        ],
        "interview_enabled": event.interview_enabled,
        "starts_at": iso(event.starts_at),
        "created_at": iso(event.created_at),
        "share_url": share_url(event.id),
        "host": {"user_id": host.id, "name": host.name} if host else None,
        "my_membership": my_membership,
        "stats": {"member_count": member_count, "groups_formed": groups_formed},
    }


# --- join validation --------------------------------------------------------------------------

def _invalid(message: str) -> AppError:
    return AppError(422, "invalid_answers", message)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _clean_answer(q: Question, value: Any) -> Any:
    """The normalized answer, None when it counts as unanswered, or 422 `invalid_answers`."""
    if value is None:
        return None
    if q.kind == "text":
        if not isinstance(value, str):
            raise _invalid(f"Question {q.id} expects text")
        value = value.strip()
        if len(value) > MAX_TEXT_ANSWER:
            raise _invalid(f"Answer to {q.id} is too long (max {MAX_TEXT_ANSWER} characters)")
        return value or None
    if q.kind == "number":
        if not _is_number(value):
            raise _invalid(f"Question {q.id} expects a number")
        return value
    options = q.options or []
    if q.kind == "single_choice":
        if not isinstance(value, str) or value not in options:
            raise _invalid(f"Answer to {q.id} must be one of its options")
        return value
    # multi_choice
    if not isinstance(value, list) or any(not isinstance(v, str) or v not in options for v in value):
        raise _invalid(f"Answer to {q.id} must be a list of its options")
    value = list(dict.fromkeys(value))
    return value or None


def validate_answers(questions: list[Question], raw: list[tuple[str, Any]]) -> dict[str, Any]:
    by_id = {q.id: q for q in questions}
    answers: dict[str, Any] = {}
    seen: set[str] = set()
    for question_id, value in raw:
        q = by_id.get(question_id)
        if q is None:
            raise _invalid(f"Unknown question {question_id}")
        if question_id in seen:
            raise _invalid(f"Question {question_id} is answered twice")
        seen.add(question_id)
        cleaned = _clean_answer(q, value)
        if cleaned is not None:
            answers[question_id] = cleaned
    missing = [q.id for q in questions if q.required and q.id not in answers]
    if missing:
        raise _invalid(f"Missing required answers: {', '.join(missing)}")
    return answers


def _clean_field(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool) or _is_number(value):
        return value
    if isinstance(value, str):
        value = value.strip()
        if len(value) > MAX_FIELD_TEXT:
            raise _invalid(f"Field {key} is too long (max {MAX_FIELD_TEXT} characters)")
        return value or None
    if isinstance(value, list):
        if len(value) > MAX_FIELD_LIST or any(
            not isinstance(v, str) or len(v) > MAX_FIELD_ITEM for v in value
        ):
            raise _invalid(
                f"Field {key} must be a list of at most {MAX_FIELD_LIST} short strings"
            )
        items = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        return items or None
    raise _invalid(f"Field {key} must be text, a number, true/false or a list of text")


def validate_fields(required_fields: list[str], raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(required_fields))
    if unknown:
        raise _invalid(f"Unknown fields: {', '.join(unknown)}")
    fields = {}
    for key in required_fields:
        cleaned = _clean_field(key, raw.get(key))
        if cleaned is None:
            raise _invalid(f"Missing required field: {key}")
        fields[key] = cleaned
    return fields
