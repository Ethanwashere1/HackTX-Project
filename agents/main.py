import hmac
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from agents import (
    GeminiNotConfigured,
    RecommenderError,
    env_value,
    run_gemini_interviewer,
    run_recommender_agent,
    run_summarizer_agent,
)
from interview import run_interview

app = FastAPI(title="SquadUp Gemini Agents Service")


# Errors use the contract format: {"error": {"code": ..., "message": ...}}
class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message

def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})

@app.exception_handler(ApiError)
async def handle_api_error(_: Request, exc: ApiError):
    return error_response(exc.status, exc.code, exc.message)

@app.exception_handler(GeminiNotConfigured)
async def handle_gemini_not_configured(_: Request, exc: GeminiNotConfigured):
    return error_response(503, "gemini_not_configured", "Gemini is not configured on the agents service")

@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    return error_response(422, "validation_error", "Invalid request body")

@app.exception_handler(StarletteHTTPException)
async def handle_http_error(_: Request, exc: StarletteHTTPException):
    codes = {404: "not_found", 405: "method_not_allowed"}
    return error_response(exc.status_code, codes.get(exc.status_code, "error"), str(exc.detail))


def require_internal_key(x_internal_key: Optional[str] = Header(None)) -> None:
    """Backend <-> agents calls must send X-Internal-Key (env INTERNAL_API_KEY)."""
    expected = env_value("INTERNAL_API_KEY")
    if not expected or not x_internal_key or not hmac.compare_digest(x_internal_key, expected):
        raise ApiError(401, "unauthenticated", "Missing or invalid X-Internal-Key")


class SummarizeRequest(BaseModel):
    transcript: str

# POST /recommend request (CONTRACT.md section 8)
class RecommendEvent(BaseModel):
    event_id: str
    type: Optional[str] = None
    tone: Optional[str] = None
    description: Optional[str] = ""

class RecommendViewer(BaseModel):
    user_id: str
    profile_text: str = ""

class RecommendCandidate(BaseModel):
    candidate_type: Literal["user", "group"]
    id: str
    profile_text: str = ""
    similarity: Optional[float] = None

class RecommendPayload(BaseModel):
    event: RecommendEvent
    viewer: RecommendViewer
    candidates: list[RecommendCandidate] = Field(max_length=100)
    limit: int = Field(10, ge=1, le=50)

class InterviewTurnRequest(BaseModel):
    history: list[dict]

@app.get("/health")
def health_check():
    return {"ok": True, "service": "agents"}

@app.post("/recommend", dependencies=[Depends(require_internal_key)])
async def get_recommendations(payload: RecommendPayload):
    """
    POST /recommend contract endpoint: reranks candidates with reasons.
    """
    try:
        reranked = await run_in_threadpool(
            run_recommender_agent,
            viewer_profile=payload.viewer.model_dump(),
            candidates=[c.model_dump() for c in payload.candidates],
            event_context=payload.event.model_dump(),
            limit=payload.limit,
        )
    except RecommenderError as exc:
        raise ApiError(502, "recommender_failed", str(exc))
    return {"results": reranked}

@app.post("/internal/interview-summary", dependencies=[Depends(require_internal_key)])
def summarize_interview(req: SummarizeRequest):
    """
    Turns an interview transcript into profile summary and traits.
    """
    result = run_summarizer_agent(req.transcript)
    return result

@app.post("/api/interview-turn")
def interview_turn(req: InterviewTurnRequest):
    """
    Handles turn-by-turn interview logic.
    """
    return run_gemini_interviewer(req.history)

@app.websocket("/ws/interview")
async def interview_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    input_mode: str = Query("voice", alias="input"),
):
    """
    WebSocket endpoint for Gemini Live Voice / Text interview (CONTRACT.md section 9).
    """
    await run_interview(websocket, token, input_mode)
