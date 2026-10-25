from datetime import datetime

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field, id_field


class SocialLookup(SQLModel, table=True):
    """Cached SerpAPI result for one social handle, shared by every user who lists it."""

    __tablename__ = "social_lookups"
    __table_args__ = (
        UniqueConstraint("kind", "handle", name="uq_social_lookups_kind_handle"),
        CheckConstraint("status IN ('ok', 'failed')", name="ck_social_lookups_status"),
    )

    id: str = id_field("soc")
    kind: str = Field(max_length=20)  # contact kind: github|instagram|linkedin|...
    handle: str = Field(max_length=300)  # normalized: lowercase
    status: str = Field(max_length=10)  # ok|failed
    notes: str | None = None  # public info to add to the profile; null when failed
    fetched_at: datetime = created_at_field()
