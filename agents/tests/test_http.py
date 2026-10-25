"""Boot without a key, /health, /recommend and the legacy endpoints."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import agents
from agents import (
    InterviewSummaryResponse,
    InterviewerTurn,
    ProfileOverviewResponse,
    QuizGenResponse,
    RecommenderResponse,
)
from conftest import INTERNAL_KEY

AUTH = {"X-Internal-Key": INTERNAL_KEY}
AGENTS_DIR = Path(__file__).resolve().parents[1]

RECOMMEND_BODY = {
    "event": {"event_id": "evt_h1", "type": "structured", "tone": "casual", "description": "Hackathon"},
    "viewer": {
        "user_id": "usr_a1",
        "profile_text": "Frontend dev, React",
        "traits": {"working_style": "pairing", "topics": "climate,react", "group_need": "hackathon teammates"},
        "topic_signals": ["climate", "react"],
        "group_need": "hackathon teammates",
    },
    "candidates": [
        {
            "candidate_type": "user",
            "id": "usr_b2",
            "profile_text": "Backend dev",
            "similarity": 0.83,
            "traits": {"working_style": "async", "topics": "climate,apis"},
            "topic_signals": ["climate", "apis"],
            "group_need": "hackathon teammates",
        },
        {
            "candidate_type": "group",
            "id": "grp_1",
            "profile_text": "Team needs a designer",
            "similarity": 0.79,
            "traits": {},
            "topic_signals": ["design"],
            "group_need": None,
        },
        {"candidate_type": "user", "id": "usr_c3", "profile_text": "ML person", "similarity": 0.7},
    ],
    "limit": 2,
}

OVERVIEW_BODY = {
    "user": {"user_id": "usr_a1", "name": "Ana"},
    "answers": {"q_1": "frontend", "q_2": "climate apps"},
    "fields": {"skills": ["react", "figma"], "experience_level": "intermediate"},
    "social_notes": "GitHub: climate-dashboard",
    "interview_summary": "Loves climate apps; prefers pairing.",
    "interview_traits": {"working_style": "pairing", "ambition": "win"},
    "event": {"event_id": "evt_h1", "name": "HackTX team-up", "type": "structured", "tone": "casual"},
}

QUIZ_BODY = {
    "event": {
        "name": "HackTX team-up",
        "type": "structured",
        "tone": "casual",
        "description": "Find your hackathon team",
    },
    "existing_questions": [
        {"text": "What role do you want?", "kind": "single_choice", "options": ["frontend", "backend"]}
    ],
    "count": 2,
    "hint": "availability and what they want to build",
}


def test_imports_and_boots_without_key():
    env = {**os.environ, "GEMINI_API_KEY": "REPLACE_ME"}
    code = (
        "from fastapi.testclient import TestClient; import main; "
        "r = TestClient(main.app).get('/health'); assert r.json() == {'ok': True, 'service': 'agents'}, r.text"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=AGENTS_DIR, env=env, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr


def test_get_client_fails_clearly_without_key(no_gemini):
    with pytest.raises(agents.GeminiNotConfigured):
        agents.get_client()


def test_health(client):
    assert client.get("/health").json() == {"ok": True, "service": "agents"}


def test_unknown_route_uses_error_format(client):
    resp = client.get("/nope")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Key": "wrong"}])
def test_recommend_requires_internal_key(client, fake_gemini, headers):
    resp = client.post("/recommend", json=RECOMMEND_BODY, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthenticated"
    assert fake_gemini.models.calls == []


def test_recommend_rejects_when_internal_key_unset(client, fake_gemini, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "REPLACE_ME")
    resp = client.post("/recommend", json=RECOMMEND_BODY, headers={"X-Internal-Key": "REPLACE_ME"})
    assert resp.status_code == 401


def test_recommend_filters_dedupes_clamps_and_caps(client, fake_gemini):
    def handler(schema, call):
        assert schema is RecommenderResponse
        return {"results": [
            {"id": "usr_zz", "score": 0.99, "reason": "Not a candidate"},
            {"id": "grp_1", "score": 1.7, "reason": "They need your frontend skills."},
            {"id": "grp_1", "score": 0.5, "reason": "Duplicate"},
            {"id": "usr_b2", "score": -0.2, "reason": "Covers the backend."},
            {"id": "usr_c3", "score": 0.4, "reason": "ML help."},
        ]}
    fake_gemini.models.handler = handler

    resp = client.post("/recommend", json=RECOMMEND_BODY, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {"results": [
        {"candidate_type": "group", "id": "grp_1", "score": 1.0, "reason": "They need your frontend skills."},
        {"candidate_type": "user", "id": "usr_c3", "score": 0.4, "reason": "ML help."},
    ]}
    prompt = fake_gemini.models.calls[0]["contents"]
    assert "usr_b2" in prompt and "top 2" in prompt
    assert "topic_signals" in prompt and "group_need" in prompt
    assert "climate" in prompt


def test_profile_overview_requires_key_and_works(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {
        "overview": "Frontend builder focused on climate apps.",
        "traits": {
            "working_style": "pairing",
            "ambition": "win",
            "topics": "climate,react,figma",
            "group_need": "hackathon teammates",
        },
    }
    assert client.post("/profile-overview", json=OVERVIEW_BODY).status_code == 401
    resp = client.post("/profile-overview", json=OVERVIEW_BODY, headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["overview"].startswith("Frontend")
    assert body["traits"]["topics"] == "climate,react,figma"
    assert body["traits"]["group_need"] == "hackathon teammates"
    assert fake_gemini.models.calls[0]["config"].response_schema is ProfileOverviewResponse


def test_profile_overview_merges_interview_traits(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {
        "overview": "Climate builder.",
        "traits": {"topics": "climate"},
    }
    resp = client.post("/profile-overview", json=OVERVIEW_BODY, headers=AUTH)
    assert resp.status_code == 200
    traits = resp.json()["traits"]
    assert traits["working_style"] == "pairing"
    assert traits["ambition"] == "win"
    assert traits["topics"] == "climate"


def test_profile_overview_failure_returns_502(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: (_ for _ in ()).throw(RuntimeError("boom"))
    resp = client.post("/profile-overview", json=OVERVIEW_BODY, headers=AUTH)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "overview_failed"


def test_profile_overview_without_gemini_key_returns_503(client, no_gemini):
    resp = client.post("/profile-overview", json=OVERVIEW_BODY, headers=AUTH)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "gemini_not_configured"


def test_generate_questions_filters_dupes_and_kinds(client, fake_gemini):
    def handler(schema, call):
        assert schema is QuizGenResponse
        return {"questions": [
            {"text": "What role do you want?", "kind": "single_choice",
             "options": ["frontend", "backend"], "required": True},
            {"text": "How many hours can you commit?", "kind": "single_choice",
             "options": ["under 8", "8-16", "all weekend"], "required": True},
            {"text": "What do you want to build?", "kind": "text", "options": None, "required": False},
            {"text": "Bad choice", "kind": "single_choice", "options": ["only-one"], "required": False},
            {"text": "Invalid kind", "kind": "essay", "options": None, "required": False},
        ]}
    fake_gemini.models.handler = handler

    resp = client.post("/generate-questions", json=QUIZ_BODY, headers=AUTH)
    assert resp.status_code == 200
    questions = resp.json()["questions"]
    assert len(questions) == 2
    assert questions[0]["text"] == "How many hours can you commit?"
    assert questions[0]["options"] == ["under 8", "8-16", "all weekend"]
    assert questions[1] == {
        "text": "What do you want to build?",
        "kind": "text",
        "options": None,
        "required": False,
    }


def test_generate_questions_requires_key(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {"questions": [
        {"text": "Availability?", "kind": "text", "options": None, "required": False},
    ]}
    assert client.post("/generate-questions", json=QUIZ_BODY).status_code == 401


def test_generate_questions_failure_returns_502(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {"questions": []}
    resp = client.post("/generate-questions", json=QUIZ_BODY, headers=AUTH)
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "quizgen_failed"


def test_generate_questions_without_gemini_key_returns_503(client, no_gemini):
    resp = client.post("/generate-questions", json=QUIZ_BODY, headers=AUTH)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "gemini_not_configured"


def test_generate_questions_validates_count(client, fake_gemini):
    bad = {**QUIZ_BODY, "count": 0}
    resp = client.post("/generate-questions", json=bad, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_recommend_empty_candidates_skips_gemini(client, fake_gemini):
    resp = client.post("/recommend", json={**RECOMMEND_BODY, "candidates": []}, headers=AUTH)
    assert resp.json() == {"results": []}
    assert fake_gemini.models.calls == []


@pytest.mark.parametrize("output", [
    "not json",
    {"results": [{"id": "usr_unknown", "score": 0.9, "reason": "x"}]},
    RuntimeError("Gemini 500"),
])
def test_recommend_failure_returns_5xx(client, fake_gemini, output):
    def handler(schema, call):
        if isinstance(output, Exception):
            raise output
        return output
    fake_gemini.models.handler = handler

    resp = client.post("/recommend", json=RECOMMEND_BODY, headers=AUTH)

    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "recommender_failed"


def test_recommend_without_gemini_key_returns_503(client, no_gemini):
    resp = client.post("/recommend", json=RECOMMEND_BODY, headers=AUTH)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "gemini_not_configured"


def test_recommend_validates_body(client, fake_gemini):
    bad = {**RECOMMEND_BODY, "candidates": [{"candidate_type": "robot", "id": "x"}]}
    resp = client.post("/recommend", json=bad, headers=AUTH)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_interview_summary_requires_key_and_works(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {"summary": "Frontend dev.", "traits": ["react"]}
    assert client.post("/internal/interview-summary", json={"transcript": "USER: hi"}).status_code == 401
    resp = client.post("/internal/interview-summary", json={"transcript": "USER: hi"}, headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"summary": "Frontend dev.", "traits": ["react"]}
    assert fake_gemini.models.calls[0]["config"].response_schema is InterviewSummaryResponse


def test_interview_turn_still_works(client, fake_gemini):
    fake_gemini.models.handler = lambda schema, call: {"spoken_reply": "Hi! What do you build?",
                                                       "interview_complete": False}
    resp = client.post("/api/interview-turn", json={"history": [{"role": "user", "text": "hello"}]})
    assert resp.json() == {"spoken_reply": "Hi! What do you build?", "interview_complete": False}
    call = fake_gemini.models.calls[0]
    assert call["config"].response_schema is InterviewerTurn
    assert call["config"].system_instruction == agents.INTERVIEWER_INSTRUCTION
    assert call["model"] == "gemini-3.8-flash"


def test_interview_turn_without_key_returns_503(client, no_gemini):
    resp = client.post("/api/interview-turn", json={"history": []})
    assert resp.status_code == 503


def test_ml_model_mock_still_works():
    from ml_model import recommend_candidates_mock
    ranked = recommend_candidates_mock("user-1", [{"user_id": "user-1"}, {"user_id": "user-2", "skills": ["python"]}])
    assert [r["user_id"] for r in ranked] == ["user-2"]
