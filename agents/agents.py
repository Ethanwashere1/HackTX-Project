import json
import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Load API key from api.env (keeping your exact file name)
current_dir = Path(__file__).parent
load_dotenv(current_dir / "api.env")
load_dotenv(current_dir / ".env")

PLACEHOLDERS = {"", "REPLACE_ME"}


def env_value(name: str, default: str | None = None) -> str | None:
    """Reads an env var; empty or REPLACE_ME placeholders count as unset."""
    value = (os.getenv(name) or "").strip()
    return default if value in PLACEHOLDERS else value


class GeminiNotConfigured(RuntimeError):
    """GEMINI_API_KEY is missing or still a placeholder."""


class RecommenderError(RuntimeError):
    """Gemini failed or returned an unusable rerank."""


# The client is created on first use so the service boots without a key.
_client: genai.Client | None = None
GEMINI_TIMEOUT_MS = 30_000


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = env_value("GEMINI_API_KEY")
        if not api_key:
            raise GeminiNotConfigured(
                f"GEMINI_API_KEY is not set (checked env, {current_dir / 'api.env'} and {current_dir / '.env'})."
            )
        _client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS))
    return _client


MODEL_ID = env_value("GEMINI_MODEL", "gemini-3.8-flash")
# Audio-native Live model served on the Gemini API (API key); see google-genai's live tests.
LIVE_MODEL_ID = env_value("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
FAST_THINKING = types.ThinkingConfig(thinking_budget=0)


# =========================================================
# 1. INTERVIEWER AGENT
# =========================================================
class InterviewerTurn(BaseModel):
    spoken_reply: str = Field(description="Warm, natural 1-2 sentence response asking the next interview question.")
    interview_complete: bool = Field(description="True if we have enough info on interests, skill level, group size, and time commitment.")

INTERVIEWER_INSTRUCTION = (
    "You are the SquadUp AI Interviewer. Help match the user by finding out: "
    "1) Group Category (Hackathon, Roommates, Social Club, Friends), "
    "2) Interests/skills, 3) Knowledge level (Beginner, Novice, Intermediate, Advanced), "
    "4) Ideal group size, and 5) Weekly hours commitment. Keep replies under 30 words."
)

TONE_STYLE = {
    "casual": "Be friendly, relaxed and upbeat, like a fellow participant.",
    "professional": "Be polite, concise and professional, like a recruiter.",
}


def build_interviewer_instruction(event_config: dict | None, voice: bool = False) -> str:
    """System instruction for the Interviewer, built from the backend's interview config."""
    if not event_config:
        return INTERVIEWER_INSTRUCTION
    user = event_config.get("user") or {}
    event = event_config.get("event") or {}
    questions = [q.get("text", "") for q in event_config.get("questions") or [] if q.get("text")]
    question_lines = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1)) or "(none)"
    profile = json.dumps(event_config.get("profile_so_far") or {}, ensure_ascii=False)
    max_minutes = event_config.get("max_minutes") or 5
    finish = (
        "When you have enough information, or the user wants to stop, say a short goodbye "
        "and then call the finish_interview function."
        if voice
        else "Set interview_complete to true once you have enough information, or the user wants to stop."
    )
    return (
        f"You are the SquadUp AI Interviewer. You are interviewing {user.get('name', 'the user')} for the "
        f"{event.get('type', '')} event \"{event.get('name', '')}\". Event description: {event.get('description') or '(none)'}\n"
        f"{TONE_STYLE.get(event.get('tone'), TONE_STYLE['casual'])}\n"
        "Help match the user with the right people and groups by finding out their interests/skills, "
        "knowledge level, what they want to build or do, working style, and availability.\n"
        f"Cover the host's questions:\n{question_lines}\n"
        f"Skip anything already answered in their profile so far: {profile}\n"
        f"Ask one question at a time. Keep replies under 30 words. The interview lasts at most {max_minutes} minutes. "
        + ("You are speaking out loud, so be natural and brief. " if voice else "")
        + finish
    )


def run_gemini_interviewer(conversation_history: list[dict], event_config: dict | None = None) -> dict:
    """Conducts the interview conversation turn-by-turn."""
    transcript = "\n".join([f"{msg.get('role', 'user').upper()}: {msg.get('text', '')}" for msg in conversation_history])
    response = get_client().models.generate_content(
        model=MODEL_ID,
        contents=f"Conversation so far:\n{transcript}",
        config=types.GenerateContentConfig(
            system_instruction=build_interviewer_instruction(event_config),
            response_mime_type="application/json",
            response_schema=InterviewerTurn,
            thinking_config=FAST_THINKING,
            max_output_tokens=180,
            temperature=0.3,
        ),
    )
    return InterviewerTurn.model_validate_json(response.text).model_dump()


# =========================================================
# 2. PROFILER & SUMMARIZER AGENT
# =========================================================
class InterviewSummaryResponse(BaseModel):
    summary: str = Field(description="A 2-3 sentence professional summary of the candidate based on their interview.")
    traits: list[str] = Field(description="List of 3-5 key technical or personality traits extracted.")


class OverviewError(RuntimeError):
    """Gemini failed or returned an unusable profile overview."""


class QuizGenError(RuntimeError):
    """Gemini failed or returned unusable questionnaire questions."""


class ProfileOverviewResponse(BaseModel):
    overview: str = Field(description="2-3 sentence profile overview for recommendations and the profile page.")
    traits: dict[str, str] = Field(
        description=(
            "Merged trait map: working_style, ambition, availability, topics (comma-separated), "
            "group_need, and any other short string traits."
        )
    )


def _clean_traits(raw: dict | None) -> dict[str, str]:
    traits: dict[str, str] = {}
    if not isinstance(raw, dict):
        return traits
    for key, value in raw.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            traits[str(key).strip()] = text
    return traits


def run_gemini_profiler(transcript: str) -> dict:
    """Turns an interview transcript into a structured profile summary and traits."""
    prompt = f"Analyze this candidate interview transcript and extract a professional summary and key traits:\n\n{transcript}"

    response = get_client().models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are the SquadUp Profile Summarizer. Extract concise, professional summaries "
                "and highlight key technical skills and collaboration traits."
            ),
            response_mime_type="application/json",
            response_schema=InterviewSummaryResponse,
            thinking_config=FAST_THINKING,
            max_output_tokens=300,
            temperature=0.2,
        ),
    )
    return InterviewSummaryResponse.model_validate_json(response.text).model_dump()


# Alias for main.py imports
run_summarizer_agent = run_gemini_profiler


def run_profile_overview_agent(payload: dict) -> dict:
    """Build a shared profile overview + merged traits from answers, socials, and interview."""
    prompt = (
        "Build a short SquadUp profile overview and merged traits from this input.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        response = get_client().models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are the SquadUp Profiler. Write a 2-3 sentence overview that helps teammates "
                    "decide whether to connect. Merge interview traits with topics and group_need inferred "
                    "from questionnaire answers, fields, and social notes. topics should be a comma-separated "
                    "lowercase string of interests/skills. group_need should say what kind of people or group "
                    "they are looking for. Keep traits values short strings. Match the event tone when present."
                ),
                response_mime_type="application/json",
                response_schema=ProfileOverviewResponse,
                thinking_config=FAST_THINKING,
                max_output_tokens=400,
                temperature=0.2,
            ),
        )
        parsed = ProfileOverviewResponse.model_validate_json(response.text or "")
    except GeminiNotConfigured:
        raise
    except Exception as exc:
        raise OverviewError(f"Overview failed: {exc.__class__.__name__}") from exc

    overview = parsed.overview.strip()
    if not overview:
        raise OverviewError("Overview returned empty text.")
    traits = _clean_traits(parsed.traits)
    # Keep interview traits when the model drops them.
    interview_traits = payload.get("interview_traits") or {}
    if isinstance(interview_traits, dict):
        for key, value in interview_traits.items():
            if key not in traits and value is not None and str(value).strip():
                traits[str(key)] = str(value).strip()
    return {"overview": overview, "traits": traits}


# =========================================================
# 2b. QUIZGEN — host questionnaire suggestions
# =========================================================
QUESTION_KINDS = frozenset({"text", "single_choice", "multi_choice", "number"})


class QuizQuestion(BaseModel):
    text: str = Field(description="Question shown to joiners.")
    kind: str = Field(description="One of: text, single_choice, multi_choice, number.")
    options: list[str] | None = Field(
        default=None,
        description="Required unique options for single_choice/multi_choice; null for text/number.",
    )
    required: bool = Field(default=False, description="Whether the joiner must answer.")


class QuizGenResponse(BaseModel):
    questions: list[QuizQuestion]


def _normalize_quiz_question(raw: QuizQuestion, existing_texts: set[str]) -> dict | None:
    text = raw.text.strip()
    kind = (raw.kind or "").strip().lower()
    if not text or kind not in QUESTION_KINDS:
        return None
    if text.casefold() in existing_texts:
        return None
    options = raw.options
    if kind in ("single_choice", "multi_choice"):
        cleaned = []
        seen_opts: set[str] = set()
        for opt in options or []:
            o = str(opt).strip()
            if not o or o.casefold() in seen_opts:
                continue
            seen_opts.add(o.casefold())
            cleaned.append(o)
        if len(cleaned) < 2:
            return None
        options = cleaned
    else:
        options = None
    existing_texts.add(text.casefold())
    return {
        "text": text,
        "kind": kind,
        "options": options,
        "required": bool(raw.required),
    }


def run_quizgen_agent(
    event: dict,
    existing_questions: list[dict] | None = None,
    count: int = 3,
    hint: str | None = None,
) -> list[dict]:
    """Suggest questionnaire questions for the host. Does not create an event."""
    count = max(1, min(10, int(count or 3)))
    existing = existing_questions or []
    existing_texts = {str(q.get("text", "")).strip().casefold() for q in existing if q.get("text")}
    prompt = (
        f"Event: {json.dumps(event, ensure_ascii=False)}\n"
        f"Existing questions (do not duplicate texts): {json.dumps(existing, ensure_ascii=False)}\n"
        f"Hint: {hint or '(none)'}\n"
        f"Propose exactly {count} new short assessment questions for joiners."
    )
    try:
        response = get_client().models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are SquadUp QuizGen. Suggest short questionnaire questions for event hosts. "
                    "Prefer kinds that fit the tone: casual events can use friendly wording; professional "
                    "events stay concise. Use single_choice or multi_choice when options help matching; "
                    "text for open goals; number for hours/capacity. Never duplicate existing question text. "
                    "Keep question text under 200 characters."
                ),
                response_mime_type="application/json",
                response_schema=QuizGenResponse,
                thinking_config=FAST_THINKING,
                max_output_tokens=900,
                temperature=0.4,
            ),
        )
        parsed = QuizGenResponse.model_validate_json(response.text or "")
    except GeminiNotConfigured:
        raise
    except Exception as exc:
        raise QuizGenError(f"QuizGen failed: {exc.__class__.__name__}") from exc

    questions: list[dict] = []
    for item in parsed.questions:
        normalized = _normalize_quiz_question(item, existing_texts)
        if normalized:
            questions.append(normalized)
        if len(questions) >= count:
            break
    if not questions:
        raise QuizGenError("QuizGen returned no valid questions.")
    return questions[:count]


# =========================================================
# 3. MATCHMAKER & RECOMMENDER AGENT
# =========================================================
class RecommendationItem(BaseModel):
    id: str = Field(description="The candidate's id, copied exactly from the input.")
    score: float = Field(description="Compatibility score from 0.0 to 1.0.")
    reason: str = Field(description="One short sentence on why they fit well together, addressed to the viewer.")


class RecommenderResponse(BaseModel):
    results: list[RecommendationItem]


def run_gemini_matchmaker(viewer_profile: dict, candidates: list[dict], event_context: dict, limit: int = 10) -> list[dict]:
    """
    Reranks candidates for an event, providing a custom recommendation reason for each.
    Returns contract-shaped results ({candidate_type, id, score, reason}) using only the given ids.
    Raises RecommenderError on a Gemini failure or invalid output (the backend then falls back to similarity order).
    """
    if not candidates:
        return []
    prompt = f"""
    Viewer Profile: {json.dumps(viewer_profile, ensure_ascii=False)}
    Event Context: {json.dumps(event_context, ensure_ascii=False)}
    Candidates/Groups to evaluate: {json.dumps(candidates, ensure_ascii=False)}

    Rerank these candidates into the top {limit}. For each, provide a short reason why they fit well together.
    Weigh: overlapping topic_signals / prior similar interests, complementary skills, shared group_need,
    and traits that suggest they work well together (working_style, ambition, availability) — not only
    raw profile_text similarity. Mention the strongest signal in the reason when possible.
    """

    try:
        response = get_client().models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are the SquadUp Recommender Agent. Evaluate compatibility using profile text plus "
                    "optional traits, topic_signals, and group_need. Prefer people who share topics or "
                    "complement skills and who want a similar kind of group. Return JSON with 'results': "
                    "objects with 'id' (copied exactly from the candidates), 'score' (0.0-1.0), and a concise "
                    "'reason' that matches the event's tone. Only use ids from the candidates."
                ),
                response_mime_type="application/json",
                response_schema=RecommenderResponse,
                thinking_config=FAST_THINKING,
                max_output_tokens=1500,
                temperature=0.3,
            ),
        )
        parsed = RecommenderResponse.model_validate_json(response.text or "")
    except GeminiNotConfigured:
        raise
    except Exception as exc:
        raise RecommenderError(f"Recommender failed: {exc.__class__.__name__}") from exc

    by_id = {c["id"]: c for c in candidates}
    results, seen = [], set()
    for item in parsed.results:
        reason = item.reason.strip()
        if item.id not in by_id or item.id in seen or not reason:
            continue
        seen.add(item.id)
        results.append({
            "candidate_type": by_id[item.id]["candidate_type"],
            "id": item.id,
            "score": round(min(1.0, max(0.0, item.score)), 4),
            "reason": reason,
        })
    if not results:
        raise RecommenderError("Recommender returned no valid candidates.")
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


# Alias for main.py imports
run_recommender_agent = run_gemini_matchmaker
