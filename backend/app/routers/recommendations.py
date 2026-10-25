"""Contract section 4: GET /api/events/{event_id}/recommendations (event members only)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.auth.deps import CurrentUser, DbSession
from app.errors import AppError
from app.services import recommendations as svc
from app.services.events import get_membership, get_visible_event

router = APIRouter(prefix="/api/events", tags=["recommendations"])


@router.get("/{event_id}/recommendations")
def get_recommendations(
    event_id: str,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
):
    event = get_visible_event(db, event_id, user)
    member = get_membership(db, event.id, user.id)
    if member is None:
        raise AppError(403, "forbidden", "Join the event to see recommendations")
    return svc.recommend(db, event, member, limit)
