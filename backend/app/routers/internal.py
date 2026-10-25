"""Contract section 8: endpoints the agents service calls (X-Internal-Key). Endpoints to come."""

from fastapi import APIRouter

router = APIRouter(prefix="/internal", tags=["internal"])
