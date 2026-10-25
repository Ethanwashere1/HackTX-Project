"""Contract section 8: endpoints the agents service calls, authenticated with X-Internal-Key."""

import hmac
import json
import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.auth.deps import DbSession
from app.config import get_settings
from app.errors import AppError
from app.services import interviews as svc
from app.services import profiles as profile_svc

log = logging.getLogger(__name__)

MAX_TRAITS_JSON = 10_000  # characters


def require_internal_key(
    x_internal_key: Annotated[str | None, Header(alias="X-Internal-Key")] = None,
) -> None:
    """401 without the header, 403 for a wrong key. Fails closed while INTERNAL_API_KEY is unset."""
    if not x_internal_key:
        raise AppError(401, "unauthenticated", "Missing X-Internal-Key")
    settings = get_settings()
    if not settings.internal_key_configured:
        log.warning("INTERNAL_API_KEY is not configured; rejecting an internal call")
        raise AppError(403, "forbidden", "Invalid X-Internal-Key")
    if not hmac.compare_digest(x_internal_key.encode(), settings.internal_api_key.encode()):
        raise AppError(403, "forbidden", "Invalid X-Internal-Key")


router = APIRouter(
    prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_key)]
)


class TranscriptEntry(BaseModel):
    role: Literal["interviewer", "user"]
    text: str = Field(max_length=5000)
    ts: str | None = Field(default=None, max_length=40)


class SummaryBody(BaseModel):
    transcript: list[TranscriptEntry] = Field(default_factory=list, max_length=1000)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
    traits: dict[str, Any] = Field(default_factory=dict, max_length=50)
    input_mode: Literal["voice", "text"] | None = None

    @field_validator("traits")
    @classmethod
    def _traits_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, ensure_ascii=False)) > MAX_TRAITS_JSON:
            raise ValueError(f"traits must be at most {MAX_TRAITS_JSON} characters as JSON")
        return v


@router.get("/interviews/{interview_token}/config")
def interview_config(interview_token: str, db: DbSession):
    return svc.claim_for_config(db, interview_token)


@router.post("/interviews/{interview_token}/summary")
def interview_summary(
    interview_token: str, body: SummaryBody, db: DbSession, background: BackgroundTasks
):
    member_ids = svc.save_summary(
        db,
        interview_token,
        summary=body.summary,
        traits=body.traits,
        transcript=[t.model_dump() for t in body.transcript],
        input_mode=body.input_mode,
    )
    # Re-embed after the response, like a join; failures are logged and never affect the save.
    background.add_task(profile_svc.run_hook, profile_svc.on_member_text_changed, member_ids)
    return {"ok": True}
