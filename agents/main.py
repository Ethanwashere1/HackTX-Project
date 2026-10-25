import hmac
import json
from typing import Annotated, Any, Literal, Optional

from fastapi import Depends, FastAPI, Header, Query, Request, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, BeforeValidator, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from agents import (
    GeminiNotConfigured,
    OverviewError,
    QuizGenError,
    RecommenderError,
    env_value,
    run_gemini_interviewer,
    run_profile_overview_agent,
    run_quizgen_agent,
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

def _stringify_traits(value: Any) -> Any:
    """Coerce trait values to short strings so stored traits never 422.

    profile.traits can hold non-string values (interview.py posts {"highlights": [...]}), and the
    backend forwards them as-is to /recommend and /profile-overview. Lists join with ", ",
    objects become JSON, empty values are dropped. Non-dict input is left for normal validation.
    """
    if not isinstance(value, dict):
        return value
    out: dict[str, str] = {}
    for key, raw in value.items():
        if raw is None:
            continue
        if isinstance(raw, (list, tuple)):
            text = ", ".join(str(x).strip() for x in raw if x is not None and str(x).strip())
        elif isinstance(raw, dict):
            text = json.dumps(raw, ensure_ascii=False)
        else:
            text = str(raw)
        if text.strip():
            out[str(key)] = text.strip()
    return out

# Trait map: string values (contract shape); other JSON values are coerced, not rejected.
Traits = Annotated[dict[str, str], BeforeValidator(_stringify_traits)]

# POST /recommend request (CONTRACT.md section 8)
class RecommendEvent(BaseModel):
    event_id: str
    type: Optional[str] = None
    tone: Optional[str] = None
    description: Optional[str] = ""

class RecommendViewer(BaseModel):
    user_id: str
    profile_text: str = ""
    traits: Traits = Field(default_factory=dict)
    topic_signals: list[str] = Field(default_factory=list)
    group_need: Optional[str] = None

class RecommendCandidate(BaseModel):
    candidate_type: Literal["user", "group"]
    id: str
    profile_text: str = ""
    similarity: Optional[float] = None
    traits: Traits = Field(default_factory=dict)
    topic_signals: list[str] = Field(default_factory=list)
    group_need: Optional[str] = None

class RecommendPayload(BaseModel):
    event: RecommendEvent
    viewer: RecommendViewer
    candidates: list[RecommendCandidate] = Field(max_length=100)
    limit: int = Field(10, ge=1, le=50)

class ProfileOverviewEvent(BaseModel):
    event_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    tone: Optional[str] = None

class ProfileOverviewUser(BaseModel):
    user_id: str
    name: Optional[str] = None

class ProfileOverviewPayload(BaseModel):
    user: ProfileOverviewUser
    answers: dict = Field(default_factory=dict)
    fields: dict = Field(default_factory=dict)
    social_notes: Optional[str] = None
    interview_summary: Optional[str] = None
    interview_traits: Traits = Field(default_factory=dict)
    event: Optional[ProfileOverviewEvent] = None

class ExistingQuestion(BaseModel):
    text: str
    kind: Optional[str] = None
    options: Optional[list[str]] = None

class GenerateQuestionsEvent(BaseModel):
    name: str = ""
    type: Optional[str] = None
    tone: Optional[str] = None
    description: Optional[str] = ""

class GenerateQuestionsPayload(BaseModel):
    event: GenerateQuestionsEvent
    existing_questions: list[ExistingQuestion] = Field(default_factory=list)
    count: int = Field(3, ge=1, le=10)
    hint: Optional[str] = None

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

@app.post("/profile-overview", dependencies=[Depends(require_internal_key)])
async def profile_overview(payload: ProfileOverviewPayload):
    """POST /profile-overview: questionnaire + socials + interview → overview + traits."""
    try:
        result = await run_in_threadpool(run_profile_overview_agent, payload.model_dump())
    except OverviewError as exc:
        raise ApiError(502, "overview_failed", str(exc))
    return result

@app.post("/generate-questions", dependencies=[Depends(require_internal_key)])
async def generate_questions(payload: GenerateQuestionsPayload):
    """POST /generate-questions: host questionnaire AI assist (QuizGen)."""
    try:
        questions = await run_in_threadpool(
            run_quizgen_agent,
            event=payload.event.model_dump(),
            existing_questions=[q.model_dump() for q in payload.existing_questions],
            count=payload.count,
            hint=payload.hint,
        )
    except QuizGenError as exc:
        raise ApiError(502, "quizgen_failed", str(exc))
    return {"questions": questions}

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
