"""Contract section 4: GET /api/events/{event_id}/recommendations. Endpoint to come."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/events", tags=["recommendations"])
