"""Shared column helpers for SQLModel tables."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.ids import id_factory


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    """ISO 8601 UTC with a Z suffix, e.g. 2026-10-25T15:00:00Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def id_field(prefix: str) -> Any:
    return Field(default_factory=id_factory(prefix), primary_key=True, max_length=40)


def fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE", index: bool = True) -> Any:
    if nullable:
        return Field(default=None, foreign_key=target, ondelete=ondelete, index=index, nullable=True)
    return Field(foreign_key=target, ondelete=ondelete, index=index)


def created_at_field() -> Any:
    return Field(default_factory=utcnow, sa_type=DateTime(timezone=True), nullable=False)


def ts_field() -> Any:
    """Nullable timestamp."""
    return Field(default=None, sa_type=DateTime(timezone=True), nullable=True)


def json_field(factory=dict) -> Any:
    return Field(default_factory=factory, sa_type=JSONB, nullable=False)


def json_nullable_field() -> Any:
    return Field(default=None, sa_type=JSONB, nullable=True)
