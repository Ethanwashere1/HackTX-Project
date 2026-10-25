from datetime import datetime
from typing import Any

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field, fk, id_field, json_field, ts_field


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = id_field("usr")
    email: str = Field(unique=True, max_length=320)  # stored lowercase
    name: str = Field(max_length=200)
    avatar_url: str | None = Field(default=None, max_length=1000)
    google_sub: str | None = Field(default=None, unique=True, max_length=255)
    created_at: datetime = created_at_field()
    updated_at: datetime = created_at_field()


class ContactMethod(SQLModel, table=True):
    """Contact info (discord, phone, ...). Only shown to group-mates and connections."""

    __tablename__ = "contact_methods"

    id: str = id_field("cm")
    user_id: str = fk("users.id")
    kind: str = Field(max_length=20)  # discord|phone|email|instagram|facebook|linkedin|github|other
    value: str = Field(max_length=300)
    position: int = 0
    created_at: datetime = created_at_field()


class Profile(SQLModel, table=True):
    """A person's profile, one per user and shared across every event they join.

    Joining an event merges the submitted socials in; an interview updates the summary. The
    per-event match text and embedding live on EventMember (profile_text, embedding).
    """

    __tablename__ = "profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_profiles_user"),)

    id: str = id_field("prf")
    user_id: str = fk("users.id", index=False)
    summary: str | None = None  # from the interview Summarizer
    traits: dict[str, Any] = json_field(dict)
    transcript: list[dict[str, Any]] = json_field(list)
    interview_input_mode: str | None = Field(default=None, max_length=10)  # voice|text
    social_notes: str | None = None  # public info found by the SerpAPI lookup
    # [{kind, value}]; a join replaces the handles of each kind it submits.
    socials: list[dict[str, Any]] = json_field(list)
    updated_at: datetime = created_at_field()


class UserSession(SQLModel, table=True):
    """Server-side login session; the cookie holds the raw token, the DB only its SHA-256."""

    __tablename__ = "user_sessions"

    token_hash: str = Field(primary_key=True, max_length=64)
    user_id: str = fk("users.id")
    created_at: datetime = created_at_field()
    expires_at: datetime = created_at_field()


class InterviewToken(SQLModel, table=True):
    """Short-lived interview token (itk_...) handed to the agents service; stored hashed."""

    __tablename__ = "interview_tokens"

    token_hash: str = Field(primary_key=True, max_length=64)
    user_id: str = fk("users.id")
    event_id: str = fk("events.id")
    created_at: datetime = created_at_field()
    expires_at: datetime = created_at_field()
    used_at: datetime | None = ts_field()
