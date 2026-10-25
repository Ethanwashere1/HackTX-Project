"""Contract section 3: create, view and join events, and start the optional interview.
Plus the connections list from section 7."""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import null
from sqlalchemy.exc import IntegrityError

from app.auth.deps import CurrentUser, DbSession
from app.auth.sessions import hash_token
from app.config import get_settings
from app.errors import AppError
from app.models import Event, EventMember, InterviewToken, Question
from app.models.base import utcnow
from app.routers.me import ContactIn
from app.services import events as svc
from app.services import profiles as profile_svc
from app.services.groups import connections_payload

router = APIRouter(prefix="/api/events", tags=["events"])

INTERVIEW_TOKEN_TTL = 600  # seconds

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
FieldKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,49}$")]


class QuestionIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    kind: Literal["text", "single_choice", "multi_choice", "number"]
    options: list[Text200] | None = Field(default=None, max_length=50)
    required: bool = False

    @model_validator(mode="after")
    def _options_match_kind(self):
        if self.kind in ("single_choice", "multi_choice"):
            if not self.options:
                raise ValueError(f"{self.kind} questions need options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("question options must be unique")
        elif self.options is not None:
            raise ValueError(f"{self.kind} questions take no options")
        return self


class EventCreate(BaseModel):
    org_id: str | None = None
    name: Text200
    description: str = Field(default="", max_length=5000)
    type: Literal["structured", "informal"]
    tone: Literal["professional", "casual"]
    group_count: int | None = Field(default=None, ge=1, le=1000)
    min_size: int | None = Field(default=None, ge=1, le=1000)
    max_size: int | None = Field(default=None, ge=1, le=1000)
    max_groups_per_user: int | None = Field(default=None, ge=1, le=100)
    required_fields: list[FieldKey] = Field(default_factory=list, max_length=20)
    questions: list[QuestionIn] = Field(default_factory=list, max_length=30)
    interview_enabled: bool = False
    starts_at: datetime | None = None

    @field_validator("starts_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @model_validator(mode="after")
    def _group_settings(self):
        group_settings = ("group_count", "min_size", "max_size", "max_groups_per_user")
        if self.type == "informal":
            given = [k for k in group_settings if getattr(self, k) is not None]
            if given:
                raise ValueError(f"informal events have no groups; omit {', '.join(given)}")
        else:
            missing = [k for k in group_settings[:3] if getattr(self, k) is None]
            if missing:
                raise ValueError(f"structured events need {', '.join(missing)}")
            if self.min_size > self.max_size:
                raise ValueError("min_size must not exceed max_size")
            if self.max_groups_per_user is None:
                self.max_groups_per_user = 1
        if len(set(self.required_fields)) != len(self.required_fields):
            raise ValueError("required_fields must be unique")
        return self


class AnswerIn(BaseModel):
    question_id: str = Field(max_length=40)
    value: Any = None


class JoinBody(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list, max_length=100)
    fields: dict[str, Any] = Field(default_factory=dict, max_length=50)
    socials: list[ContactIn] = Field(default_factory=list, max_length=10)


@router.post("", status_code=201)
def create_event(body: EventCreate, user: CurrentUser, db: DbSession):
    if body.org_id is not None:
        svc.require_org_member(db, body.org_id, user)
    event = Event(
        org_id=body.org_id,
        host_id=user.id,
        name=body.name,
        description=body.description.strip(),
        type=body.type,
        tone=body.tone,
        group_count=body.group_count,
        min_size=body.min_size,
        max_size=body.max_size,
        # Explicit NULL for informal events; the ORM would otherwise let the server default (1) apply.
        max_groups_per_user=(
            null() if body.max_groups_per_user is None else body.max_groups_per_user
        ),
        required_fields=list(body.required_fields),
        interview_enabled=body.interview_enabled,
        starts_at=body.starts_at,
    )
    db.add(event)
    db.flush()
    for i, q in enumerate(body.questions):
        db.add(
            Question(
                event_id=event.id, position=i, text=q.text, kind=q.kind,
                options=q.options, required=q.required,
            )
        )
    db.commit()
    return {"event_id": event.id, "share_url": svc.share_url(event.id)}


@router.get("/{event_id}")
def get_event(event_id: str, user: CurrentUser, db: DbSession):
    event = svc.get_visible_event(db, event_id, user)
    return svc.event_payload(db, event, user)


@router.post("/{event_id}/join", status_code=201)
def join_event(
    event_id: str, body: JoinBody, user: CurrentUser, db: DbSession, background: BackgroundTasks
):
    event = svc.get_visible_event(db, event_id, user)
    if event.host_id == user.id:
        raise AppError(
            403,
            "is_host",
            "You're the host of this event — hosts manage the event and can't join as a participant",
        )
    if svc.get_membership(db, event.id, user.id) is not None:
        raise AppError(409, "already_joined", "You already joined this event")
    questions = svc.event_questions(db, event.id)
    answers = svc.validate_answers(questions, [(a.question_id, a.value) for a in body.answers])
    fields = svc.validate_fields(event.required_fields, body.fields)
    socials = [{"kind": s.kind, "value": s.value} for s in body.socials]

    try:
        # The person profile is shared across events: submitted socials replace the same kinds.
        profile = profile_svc.get_or_create_profile(db, user.id, lock=True)
        merged = profile_svc.merge_socials(profile.socials, socials)
        socials_changed = merged != profile.socials
        if socials_changed:
            profile.socials = merged
            profile.updated_at = utcnow()
            db.add(profile)
        db.add(EventMember(event_id=event.id, user_id=user.id, answers=answers, fields=fields))
        db.flush()
        # New socials change the text of every event the user is in, not just this one.
        member_ids = profile_svc.rebuild_member_texts(
            db, user.id, None if socials_changed else [event.id]
        )
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent join by the same user won the unique constraint
        raise AppError(409, "already_joined", "You already joined this event")
    # After the response; failures are logged and never affect the join.
    background.add_task(profile_svc.run_hook, profile_svc.on_member_text_changed, member_ids)
    if socials:
        background.add_task(profile_svc.run_hook, profile_svc.schedule_social_lookup, user.id, socials)
    return {
        "event_id": event.id,
        "profile_status": "ready",
        "interview": {"available": event.interview_enabled},
    }


@router.post("/{event_id}/interview", status_code=201)
def start_interview(event_id: str, user: CurrentUser, db: DbSession):
    event = svc.get_visible_event(db, event_id, user)
    if svc.get_membership(db, event.id, user.id) is None:
        raise AppError(403, "forbidden", "Join the event before starting the interview")
    if not event.interview_enabled:
        raise AppError(409, "interview_disabled", "This event has no interview")
    token = "itk_" + secrets.token_urlsafe(32)
    now = utcnow()
    db.add(
        InterviewToken(
            token_hash=hash_token(token),
            user_id=user.id,
            event_id=event.id,
            created_at=now,
            expires_at=now + timedelta(seconds=INTERVIEW_TOKEN_TTL),
        )
    )
    db.commit()
    return {
        "ws_url": get_settings().interview_ws_url,
        "interview_token": token,
        "expires_in": INTERVIEW_TOKEN_TTL,
    }


@router.get("/{event_id}/connections")
def list_connections(event_id: str, user: CurrentUser, db: DbSession):
    """The user's connections (informal events; always empty for structured ones), with contacts."""
    event = svc.get_visible_event(db, event_id, user)
    if svc.get_membership(db, event.id, user.id) is None:
        raise AppError(403, "forbidden", "Join the event to see your connections")
    return {"connections": connections_payload(db, event.id, user.id)}
