"""Chat threads: participants, messages and the stable Jitsi call link."""

import secrets

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, delete, select, update

from app.errors import AppError
from app.models import Message, Thread, ThreadParticipant, User
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


def message_payload(m: Message) -> dict:
    return {"message_id": m.id, "sender_id": m.sender_id, "text": m.text, "sent_at": iso(m.sent_at)}


def list_messages(db: Session, thread_id: str, *, after: str | None, limit: int) -> list[dict]:
    """Oldest first. Message ids sort by creation time, so `after` pages forward by id."""
    q = select(Message).where(Message.thread_id == thread_id)
    if after:
        q = q.where(Message.id > after)
    rows = db.exec(q.order_by(Message.id).limit(limit)).all()
    return [message_payload(m) for m in rows]


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
