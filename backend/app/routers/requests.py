"""Contract section 5: requests with mutual consent."""

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator

from app.auth.deps import CurrentUser, DbSession
from app.services import requests as svc

router = APIRouter(prefix="/api/requests", tags=["requests"])


class RequestCreate(BaseModel):
    event_id: str = Field(max_length=40)
    target_type: Literal["user", "group"]
    target_id: str = Field(max_length=40)
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("message")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return (v.strip() or None) if v is not None else None


@router.post("", status_code=201)
def create_request(body: RequestCreate, user: CurrentUser, db: DbSession):
    req = svc.create_request(
        db, user, event_id=body.event_id, target_type=body.target_type,
        target_id=body.target_id, message=body.message,
    )
    return {"request_id": req.id, "status": req.status, "thread_id": req.thread_id}


@router.get("")
def list_requests(
    user: CurrentUser,
    db: DbSession,
    box: Literal["incoming", "outgoing"] = "incoming",
    event_id: str | None = Query(default=None, max_length=40),
):
    return {"requests": svc.list_requests(db, user, box=box, event_id=event_id)}


@router.post("/{request_id}/accept")
def accept_request(request_id: str, user: CurrentUser, db: DbSession):
    return svc.decision_payload(svc.accept_request(db, request_id, user))


@router.post("/{request_id}/decline")
def decline_request(request_id: str, user: CurrentUser, db: DbSession):
    return svc.decision_payload(svc.decline_request(db, request_id, user))


@router.post("/{request_id}/cancel")
def cancel_request(request_id: str, user: CurrentUser, db: DbSession):
    return svc.decision_payload(svc.cancel_request(db, request_id, user))
