"""Chat threads: participants, messages and the stable Jitsi call link."""

import secrets

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, delete, select, update

from app.errors import AppError
from app.models import Connection, Group, Message, Request, Thread, ThreadParticipant, User
from app.models.base import iso

JITSI_BASE_URL = "https://meet.jit.si"


def _new_call_room(thread_id: str) -> str:
    # The random suffix makes the public Jitsi room unguessable from the thread id.
    return f"squadup-{thread_id.replace('_', '')}-{secrets.token_hex(8)}"


def create_thread(db: Session, *, event_id: str, kind: str, user_ids: list[str]) -> Thread:
    """A new thread (kind `request` or `group`) with these participants. Flushes, no commit."""
    thread = Thread(event_id=event_id, kind=kind)
    thread.call_room = _new_call_room(thread.id)
    db.add(thread)
    db.flush()
    add_participants(db, thread.id, user_ids)
    return thread


def add_participants(db: Session, thread_id: str, user_ids: list[str]) -> None:
    """Add users to a thread; already-present users are skipped."""
    if not user_ids:
        return
    db.exec(
        pg_insert(ThreadParticipant)
        .values([{"thread_id": thread_id, "user_id": u} for u in dict.fromkeys(user_ids)])
        .on_conflict_do_nothing(index_elements=["thread_id", "user_id"])
    )


def remove_participant(db: Session, thread_id: str, user_id: str) -> None:
    db.exec(
        delete(ThreadParticipant).where(
            ThreadParticipant.thread_id == thread_id, ThreadParticipant.user_id == user_id
        )
    )


def is_participant(db: Session, thread_id: str, user_id: str) -> bool:
    return db.get(ThreadParticipant, (thread_id, user_id)) is not None


def get_thread_for_participant(db: Session, thread_id: str, user: User) -> Thread:
    """404 for an unknown thread, 403 `forbidden` for a non-participant."""
    thread = db.get(Thread, thread_id)
    if thread is None:
        raise AppError(404, "not_found", "Thread not found")
    if not is_participant(db, thread.id, user.id):
        raise AppError(403, "forbidden", "Only participants can use this thread")
    return thread


def message_payload(m: Message, sender_name: str | None) -> dict:
    return {
        "message_id": m.id,
        "sender_id": m.sender_id,
        "sender_name": sender_name,
        "text": m.text,
        "sent_at": iso(m.sent_at),
    }


def list_messages(db: Session, thread_id: str, *, after: str | None, limit: int) -> list[dict]:
    """Oldest first. Message ids sort by creation time, so `after` pages forward by id."""
    q = (
        select(Message, User.name)
        .join(User, User.id == Message.sender_id)
        .where(Message.thread_id == thread_id)
    )
    if after:
        q = q.where(Message.id > after)
    rows = db.exec(q.order_by(Message.id).limit(limit)).all()
    return [message_payload(m, name) for m, name in rows]


def _user_name(db: Session, user_id: str | None) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.name if user else None


def thread_payload(db: Session, thread: Thread, viewer: User) -> dict:
    """GET /api/threads/{id}: what the thread is about and who is in it. Caller checks access.

    Stored kinds are `request` and `group`; an informal-event connection keeps the thread of the
    request that created it, so a request thread with a connection is reported as `connection`.
    `title` is from the viewer's side: the group name for a group thread; for a request or
    connection thread the other person's name, except that a user -> group request shows the
    group name to its sender (and the sender's name to the group's members).
    """
    participants = db.exec(
        select(User.id, User.name)
        .join(ThreadParticipant, ThreadParticipant.user_id == User.id)
        .where(ThreadParticipant.thread_id == thread.id)
        .order_by(ThreadParticipant.added_at, User.id)
    ).all()
    kind, title, group_id, request_id = thread.kind, None, None, None
    if thread.kind == "group":
        group = db.exec(select(Group).where(Group.thread_id == thread.id)).first()
        if group is not None:
            group_id, title = group.id, group.name
    else:
        req = db.exec(
            select(Request).where(Request.thread_id == thread.id).order_by(Request.id)
        ).first()
        con = db.exec(select(Connection).where(Connection.thread_id == thread.id)).first()
        if con is not None:
            kind = "connection"
        if req is not None:
            request_id = req.id
            if req.target_type == "group":
                group_id = req.target_group_id
                if req.sender_id == viewer.id:
                    group = db.get(Group, req.target_group_id)
                    title = group.name if group else None
                else:
                    title = _user_name(db, req.sender_id)
            else:
                other = req.target_user_id if req.sender_id == viewer.id else req.sender_id
                title = _user_name(db, other)
        elif con is not None:
            title = _user_name(db, con.user_b_id if con.user_a_id == viewer.id else con.user_a_id)
    if title is None:
        others = [name for uid, name in participants if uid != viewer.id]
        title = others[0] if others else "Chat"
    return {
        "thread_id": thread.id,
        "kind": kind,
        "title": title,
        "event_id": thread.event_id,
        "group_id": group_id,
        "request_id": request_id,
        "participants": [{"user_id": uid, "name": name} for uid, name in participants],
    }


def call_url(db: Session, thread: Thread) -> str:
    if thread.call_room is None:
        # Threads always get a room at creation; this only covers rows made some other way.
        # The conditional update keeps the URL stable if two callers race.
        db.exec(
            update(Thread)
            .where(Thread.id == thread.id, Thread.call_room.is_(None))
            .values(call_room=_new_call_room(thread.id))
        )
        db.commit()
        db.refresh(thread)
    return f"{JITSI_BASE_URL}/{thread.call_room}"
