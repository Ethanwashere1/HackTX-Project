"""generate(): an overloaded Gemini model falls through to the next one; other errors don't."""
import pytest
from google.genai import errors as genai_errors

import agents
from agents import InterviewerTurn


def overloaded(code=503):
    return genai_errors.ServerError(code, {"error": {"code": code, "message": "high demand", "status": "UNAVAILABLE"}})


def test_overloaded_model_falls_back_to_the_next(fake_gemini):
    def handler(schema, call):
        if call["model"] == agents.MODEL_ID:
            raise overloaded(503)
        return {"spoken_reply": "What do you want to build?", "interview_complete": False}

    fake_gemini.models.handler = handler
    turn = agents.run_gemini_interviewer([{"role": "user", "text": "hi"}])
    assert turn["spoken_reply"] == "What do you want to build?"
    assert [c["model"] for c in fake_gemini.models.calls] == [agents.MODEL_ID, agents.FALLBACK_MODEL_IDS[0]]
    assert fake_gemini.models.calls[1]["config"].response_schema is InterviewerTurn


@pytest.mark.parametrize("code", [429, 500, 504])
def test_rate_limit_and_timeouts_also_fall_back(fake_gemini, code):
    def handler(schema, call):
        if call["model"] == agents.MODEL_ID:
            raise genai_errors.APIError(code, {"error": {"code": code, "message": "busy"}})
        return {"spoken_reply": "ok", "interview_complete": False}

    fake_gemini.models.handler = handler
    assert agents.run_gemini_interviewer([{"role": "user", "text": "hi"}])["spoken_reply"] == "ok"


def test_every_model_overloaded_raises_the_last_error(fake_gemini):
    fake_gemini.models.handler = lambda schema, call: (_ for _ in ()).throw(overloaded(503))
    with pytest.raises(genai_errors.ServerError):
        agents.run_gemini_interviewer([{"role": "user", "text": "hi"}])
    tried = [c["model"] for c in fake_gemini.models.calls]
    assert tried == [agents.MODEL_ID, *agents.FALLBACK_MODEL_IDS]


def test_a_bad_request_does_not_fall_back(fake_gemini):
    fake_gemini.models.handler = lambda schema, call: (_ for _ in ()).throw(
        genai_errors.ClientError(400, {"error": {"code": 400, "message": "bad request"}})
    )
    with pytest.raises(genai_errors.ClientError):
        agents.run_gemini_interviewer([{"role": "user", "text": "hi"}])
    assert len(fake_gemini.models.calls) == 1
