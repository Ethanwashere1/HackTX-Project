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

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError(f"Could not find GEMINI_API_KEY inside {current_dir / 'api.env'}.")

client = genai.Client(api_key=api_key)
MODEL_ID = "gemini-3.8-flash"
FAST_THINKING = types.ThinkingConfig(thinking_budget=0)


# =========================================================
# 1. INTERVIEWER AGENT
# =========================================================
class InterviewerTurn(BaseModel):
    spoken_reply: str = Field(description="Warm, natural 1-2 sentence response asking the next interview question.")
    interview_complete: bool = Field(description="True if we have enough info on interests, skill level, group size, and time commitment.")

def run_gemini_interviewer(conversation_history: list[dict]) -> dict:
    """Conducts the interview conversation turn-by-turn."""
    transcript = "\n".join([f"{msg.get('role', 'user').upper()}: {msg.get('text', '')}" for msg in conversation_history])
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=f"Conversation so far:\n{transcript}",
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are the SquadUp AI Interviewer. Help match the user by finding out: "
                "1) Group Category (Hackathon, Roommates, Social Club, Friends), "
                "2) Interests/skills, 3) Knowledge level (Beginner, Novice, Intermediate, Advanced), "
                "4) Ideal group size, and 5) Weekly hours commitment. Keep replies under 30 words."
            ),
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

def run_gemini_profiler(transcript: str) -> dict:
    """Turns an interview transcript into a structured profile summary and traits."""
    prompt = f"Analyze this candidate interview transcript and extract a professional summary and key traits:\n\n{transcript}"
    
    response = client.models.generate_content(
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


# =========================================================
# 3. MATCHMAKER & RECOMMENDER AGENT
# =========================================================
def run_gemini_matchmaker(viewer_profile: dict, candidates: list[dict], event_context: dict) -> list[dict]:
    """
    Reranks candidates for an event, providing a custom recommendation reason for each.
    """
    prompt = f"""
    Viewer Profile: {viewer_profile}
    Event Context: {event_context}
    Candidates/Groups to evaluate: {candidates}

    Rerank these candidates into the top N. For each, provide a short, professional reason why they fit well together.
    """
    
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=(
                "You are the SquadUp Recommender Agent. Evaluate user compatibility based on shared interests, "
                "skill levels, and event constraints. Return a JSON list of objects containing 'user_id' (or 'group_id'), "
                "'name', 'compatibility_score' (0-100), and a concise 'reason'."
            ),
            thinking_config=FAST_THINKING,
            max_output_tokens=800,
            temperature=0.3,
        ),
    )
    
    import json
    try:
        return json.loads(response.text)
    except Exception:
        return [{"id": c.get("user_id", "unknown"), "reason": "Recommended based on matching event preferences."} for c in candidates]

# Alias for main.py imports
run_recommender_agent = run_gemini_matchmaker