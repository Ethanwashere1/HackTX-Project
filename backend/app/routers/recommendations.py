"""Contract section 4: GET /api/events/{event_id}/recommendations.

Similarity search + exclusions are a separate embeddings/Snowflake task. Agents rerank
enrichment lives in `app.services.recommend` (traits / topic_signals / group_need;
people[].summary prefers overview). Wire that module when the GET endpoint lands.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/events", tags=["recommendations"])
