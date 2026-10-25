from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.config import EMBEDDING_DIM
from app.models.base import (
    created_at_field,
    fk,
    id_field,
    json_field,
    json_nullable_field,
    ts_field,
)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("type IN ('structured', 'informal')", name="ck_events_type"),
        CheckConstraint("tone IN ('professional', 'casual')", name="ck_events_tone"),
        # Structured events need all group settings; informal events have no groups.
        CheckConstraint(
            "(type = 'structured' AND group_count IS NOT NULL AND min_size IS NOT NULL"
            " AND max_size IS NOT NULL AND max_groups_per_user IS NOT NULL)"
            " OR (type = 'informal' AND group_count IS NULL AND min_size IS NULL"
            " AND max_size IS NULL)",
            name="ck_events_group_settings",
        ),
        CheckConstraint(
            "group_count > 0 AND min_size > 0 AND max_size > 0 AND max_groups_per_user > 0",
            name="ck_events_positive_sizes",
        ),
        CheckConstraint("min_size <= max_size", name="ck_events_min_le_max"),
    )

    id: str = id_field("evt")
    org_id: str | None = fk("orgs.id", nullable=True)  # null = unlisted, reachable by link only
    host_id: str = fk("users.id")
    name: str = Field(max_length=200)
    description: str = Field(default="", max_length=5000)
    type: str = Field(max_length=20)  # structured|informal
    tone: str = Field(max_length=20)  # professional|casual
    # Structured events only; null for informal events.
    group_count: int | None = None
    min_size: int | None = None
    max_size: int | None = None
    max_groups_per_user: int | None = Field(default=None, sa_column_kwargs={"server_default": "1"})
    required_fields: list[str] = json_field(list)
    interview_enabled: bool = False
    starts_at: datetime | None = ts_field()
    created_at: datetime = created_at_field()


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: str = id_field("q")
    event_id: str = fk("events.id")
    position: int = 0
    text: str = Field(max_length=1000)
    kind: str = Field(max_length=20)  # text|single_choice|multi_choice|number
    options: list[str] | None = json_nullable_field()
    required: bool = False


class EventMember(SQLModel, table=True):
    """One user's membership in one event, plus the per-event match data (text -> embedding)."""

    __tablename__ = "event_members"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_event_members_event_user"),)

    id: str = id_field("em")
    event_id: str = fk("events.id", index=False)
    user_id: str = fk("users.id")
    answers: dict[str, Any] = json_field(dict)  # {question_id: value}
    fields: dict[str, Any] = json_field(dict)  # the event's required profile fields
    joined_at: datetime = created_at_field()
    # answers + fields + the user's Profile (socials, social_notes, summary); see
    # app.services.profiles.build_member_text. This is what gets embedded and sent to the agents.
    profile_text: str = Field(default="", sa_column_kwargs={"server_default": ""})
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(EMBEDDING_DIM), nullable=True)
    )
    embedded_at: datetime | None = ts_field()
    snowflake_synced_at: datetime | None = ts_field()
