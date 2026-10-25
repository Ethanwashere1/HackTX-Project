from datetime import datetime

from sqlalchemy import CheckConstraint, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field, fk, id_field, json_field, ts_field


class Org(SQLModel, table=True):
    __tablename__ = "orgs"

    id: str = id_field("org")
    name: str = Field(max_length=200)
    verification: str = Field(default="manual", max_length=20)  # manual|email_domain|roster
    email_domains: list[str] = json_field(list)
    # Listed in GET /api/orgs for non-members (so they can request to join).
    discoverable: bool = Field(default=True, sa_column_kwargs={"server_default": "true"})
    created_by: str | None = fk("users.id", nullable=True, ondelete="SET NULL")
    created_at: datetime = created_at_field()


class OrgMember(SQLModel, table=True):
    """Membership and join request in one row per (org, user)."""

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
        Index("ix_org_members_org_status", "org_id", "status"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_org_members_role"),
        CheckConstraint("status IN ('pending', 'approved', 'declined')", name="ck_org_members_status"),
        CheckConstraint("role <> 'admin' OR status = 'approved'", name="ck_org_members_admin_approved"),
    )

    id: str = id_field("om")
    org_id: str = fk("orgs.id", index=False)
    user_id: str = fk("users.id")
    role: str = Field(default="member", max_length=10)  # admin|member
    status: str = Field(default="pending", max_length=10)  # pending|approved|declined
    message: str | None = Field(default=None, max_length=1000)
    requested_at: datetime = created_at_field()
    decided_at: datetime | None = ts_field()
    decided_by: str | None = fk("users.id", nullable=True, ondelete="SET NULL", index=False)


class OrgRosterEntry(SQLModel, table=True):
    """One row of an uploaded member list. Personal data: admins only."""

    __tablename__ = "org_roster_entries"
    __table_args__ = (
        Index("ix_org_roster_entries_org_email", "org_id", "email"),
        Index("ix_org_roster_entries_org_name", "org_id", "name_normalized"),
    )

    id: str = id_field("ros")
    org_id: str = fk("orgs.id", index=False)
    name: str | None = Field(default=None, max_length=200)
    name_normalized: str | None = Field(default=None, max_length=200)  # lowercase, single spaces
    email: str | None = Field(default=None, max_length=320)  # lowercase
    created_at: datetime = created_at_field()
