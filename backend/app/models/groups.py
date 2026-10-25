from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlmodel import Field, SQLModel

from app.models.base import created_at_field, fk, id_field, ts_field


class Thread(SQLModel, table=True):
    """Chat thread, created with each request and each group."""

    __tablename__ = "threads"

    id: str = id_field("thr")
    event_id: str | None = fk("events.id", nullable=True)
    kind: str = Field(max_length=10)  # request|group
    call_room: str | None = Field(default=None, max_length=200)  # stable Jitsi room name
    created_at: datetime = created_at_field()


class ThreadParticipant(SQLModel, table=True):
    __tablename__ = "thread_participants"

    thread_id: str = Field(foreign_key="threads.id", ondelete="CASCADE", primary_key=True)
    user_id: str = Field(foreign_key="users.id", ondelete="CASCADE", primary_key=True, index=True)
    added_at: datetime = created_at_field()


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_thread_id_id", "thread_id", "id"),)

    id: str = id_field("msg")  # time-ordered, so `after=msg_...` pages by id
    thread_id: str = fk("threads.id", index=False)
    sender_id: str = fk("users.id")
    text: str = Field(max_length=4000)
    sent_at: datetime = created_at_field()


class Group(SQLModel, table=True):
    __tablename__ = "groups"
    # Target of group_members' composite FK, so a member row can't claim another event's group.
    __table_args__ = (UniqueConstraint("id", "event_id", name="uq_groups_id_event"),)

    id: str = id_field("grp")
    event_id: str = fk("events.id")
    name: str = Field(max_length=200)
    thread_id: str | None = fk("threads.id", nullable=True, ondelete="SET NULL", index=False)
    created_at: datetime = created_at_field()


class GroupMember(SQLModel, table=True):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_members_group_user"),
        Index("ix_group_members_event_user", "event_id", "user_id"),
        ForeignKeyConstraint(
            ["group_id", "event_id"],
            ["groups.id", "groups.event_id"],
            ondelete="CASCADE",
            name="fk_group_members_group_event",
        ),
    )

    id: str = id_field("gm")
    group_id: str = Field()  # FK via fk_group_members_group_event
    event_id: str = fk("events.id", index=False)  # denormalized for max_groups_per_user checks
    user_id: str = fk("users.id", index=False)
    joined_at: datetime = created_at_field()


class Connection(SQLModel, table=True):
    """1:1 connection in an informal event. user_a_id < user_b_id so each pair is stored once."""

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("event_id", "user_a_id", "user_b_id", name="uq_connections_pair"),
        CheckConstraint("user_a_id < user_b_id", name="ck_connections_ordered"),
        Index("ix_connections_event_user_b", "event_id", "user_b_id"),
    )

    id: str = id_field("con")
    event_id: str = fk("events.id", index=False)
    user_a_id: str = fk("users.id", index=False)
    user_b_id: str = fk("users.id", index=False)
    thread_id: str | None = fk("threads.id", nullable=True, ondelete="SET NULL", index=False)
    created_at: datetime = created_at_field()


class Request(SQLModel, table=True):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(
            "(target_type = 'user' AND target_user_id IS NOT NULL AND target_group_id IS NULL)"
            " OR (target_type = 'group' AND target_group_id IS NOT NULL AND target_user_id IS NULL)",
            name="ck_requests_target",
        ),
        CheckConstraint("target_type IN ('user', 'group')", name="ck_requests_target_type"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')",
            name="ck_requests_status",
        ),
        Index("ix_requests_event_sender", "event_id", "sender_id"),
        # At most one pending request per sender and target in an event.
        Index(
            "uq_requests_pending_user", "event_id", "sender_id", "target_user_id",
            unique=True, postgresql_where=sql_text("status = 'pending' AND target_user_id IS NOT NULL"),
        ),
        Index(
            "uq_requests_pending_group", "event_id", "sender_id", "target_group_id",
            unique=True, postgresql_where=sql_text("status = 'pending' AND target_group_id IS NOT NULL"),
        ),
    )

    id: str = id_field("req")
    event_id: str = fk("events.id", index=False)
    sender_id: str = fk("users.id", index=False)
    target_type: str = Field(max_length=10)  # user|group
    target_user_id: str | None = fk("users.id", nullable=True)
    target_group_id: str | None = fk("groups.id", nullable=True)
    message: str | None = Field(default=None, max_length=1000)
    status: str = Field(default="pending", max_length=10)  # pending|accepted|declined|cancelled|expired
    thread_id: str | None = fk("threads.id", nullable=True, ondelete="SET NULL", index=False)
    created_at: datetime = created_at_field()
    decided_at: datetime | None = ts_field()
    decided_by: str | None = fk("users.id", nullable=True, ondelete="SET NULL")
    # Outcome of an accept: the group formed/joined, or the connection created.
    group_id: str | None = fk("groups.id", nullable=True, ondelete="SET NULL", index=False)
    connection_id: str | None = fk("connections.id", nullable=True, ondelete="SET NULL", index=False)
