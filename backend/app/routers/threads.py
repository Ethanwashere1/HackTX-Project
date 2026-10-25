"""Contract section 6: chat messages and the video call link (participants only)."""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from app.auth.deps import CurrentUser, DbSession
from app.errors import AppError
from app.models import Message
from app.services import threads as svc

router = APIRouter(prefix="/api/threads", tags=["threads"])


class MessageIn(BaseModel):
    text: str = Field(max_length=4000)

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be empty")
        return v


@router.get("/{thread_id}/messages")
def list_messages(
    thread_id: str,
    user: CurrentUser,
    db: DbSession,
    after: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=200),
):
    thread = svc.get_thread_for_participant(db, thread_id, user)
    return {"messages": svc.list_messages(db, thread.id, after=after, limit=limit)}


@router.post("/{thread_id}/messages", status_code=201)
def post_message(thread_id: str, body: MessageIn, user: CurrentUser, db: DbSession):
    thread = svc.get_thread_for_participant(db, thread_id, user)
    msg = Message(thread_id=thread.id, sender_id=user.id, text=body.text)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return svc.message_payload(msg)


@router.post("/{thread_id}/call")
def start_call(thread_id: str, user: CurrentUser, db: DbSession):
    thread = svc.get_thread_for_participant(db, thread_id, user)
    return {"call_url": svc.call_url(db, thread)}
