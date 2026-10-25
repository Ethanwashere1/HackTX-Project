"""Interview WebSocket (contract section 9) in text and voice mode, with fake Gemini and backend."""
import base64

import pytest
from google.genai import types
from starlette.websockets import WebSocketDisconnect

import interview
from agents import InterviewSummaryResponse, InterviewerTurn
from conftest import FakeLiveSession, receive_until

SUMMARY = {"summary": "Frontend dev who wants a chill team.", "traits": ["react", "pairing"]}


def assert_closed(ws):
    with pytest.raises(WebSocketDisconnect):
        ws.receive_json()


def scripted_text(fake_gemini, replies):
    """Interviewer replies in order; the Summarizer returns SUMMARY."""
    replies = list(replies)

    def handler(schema, call):
        if schema is InterviewerTurn:
            return replies.pop(0)
        assert schema is InterviewSummaryResponse
        return SUMMARY
    fake_gemini.models.handler = handler


def test_text_mode_end_to_end(client, fake_gemini, backend):
    scripted_text(fake_gemini, [{"spoken_reply": "Nice! How many hours can you commit?", "interview_complete": False}])

    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ready = ws.receive_json()
        assert ready == {"type": "ready",
                         "greeting_text": "Hey Ana! Thanks for joining HackTX team-up. What are you hoping to build or find here?"}
        ws.send_json({"type": "text", "text": "I mostly do React"})
        assert ws.receive_json() == {"type": "transcript", "role": "interviewer",
                                     "text": "Nice! How many hours can you commit?", "final": True}
        assert ws.receive_json() == {"type": "turn_complete"}
        ws.send_json({"type": "end"})
        done = ws.receive_json()
        assert done == {"type": "interview_complete", "summary_saved": True, "summary": SUMMARY["summary"]}
        assert_closed(ws)

    config_req = backend.requests[0]
    assert config_req.method == "GET" and config_req.headers["X-Internal-Key"] == "test-internal-key"
    [posted] = backend.summary_posts
    assert posted["input_mode"] == "text"
    assert posted["summary"] == SUMMARY["summary"]
    assert posted["traits"] == {"highlights": ["react", "pairing"]}
    assert [(t["role"], t["text"]) for t in posted["transcript"]] == [
        ("interviewer", ready["greeting_text"]),
        ("user", "I mostly do React"),
        ("interviewer", "Nice! How many hours can you commit?"),
    ]
    assert all(t["ts"].endswith("Z") for t in posted["transcript"])

    # the interviewer got the event config in its system instruction
    instruction = fake_gemini.models.calls[0]["config"].system_instruction
    assert "What role do you want?" in instruction and "HackTX team-up" in instruction
    assert "relaxed" in instruction  # casual tone
    assert "USER: I mostly do React" in fake_gemini.models.calls[1]["contents"]


def test_text_mode_finishes_when_interviewer_completes(client, fake_gemini, backend):
    backend.config = {**backend.config, "event": {**backend.config["event"], "tone": "professional"}}
    scripted_text(fake_gemini, [{"spoken_reply": "Thanks, that's all I need!", "interview_complete": True}])

    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        assert ws.receive_json()["greeting_text"].startswith("Hi Ana, welcome to HackTX team-up.")
        ws.send_json({"type": "text", "text": "Backend, all weekend"})
        messages = receive_until(ws, "interview_complete")
        assert [m["type"] for m in messages] == ["transcript", "turn_complete", "interview_complete"]
        assert messages[-1]["summary_saved"] is True
        assert_closed(ws)
    assert "professional" in fake_gemini.models.calls[0]["config"].system_instruction


def test_text_mode_time_limit(client, fake_gemini, backend, monkeypatch):
    monkeypatch.setattr(interview, "SECONDS_PER_MINUTE", 0.1)  # max_minutes 5 -> 0.5 s
    scripted_text(fake_gemini, [{"spoken_reply": "Cool, anything else?", "interview_complete": False}])

    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "Design and React"})
        messages = receive_until(ws, "interview_complete")
        assert messages[-1]["summary_saved"] is True
    assert len(backend.summary_posts) == 1


def test_end_without_answers_saves_nothing(client, fake_gemini, backend):
    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ws.receive_json()
        ws.send_json({"type": "end"})
        assert ws.receive_json() == {"type": "interview_complete", "summary_saved": False, "summary": None}
    assert backend.summary_posts == []
    assert fake_gemini.models.calls == []


def test_summary_post_failure_reports_not_saved(client, fake_gemini, backend):
    backend.summary_status = 500
    scripted_text(fake_gemini, [{"spoken_reply": "Got it!", "interview_complete": True}])
    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "React"})
        assert receive_until(ws, "interview_complete")[-1]["summary_saved"] is False


def test_summarizer_failure_sends_error(client, fake_gemini, backend):
    def handler(schema, call):
        if schema is InterviewerTurn:
            return {"spoken_reply": "Done!", "interview_complete": True}
        raise RuntimeError("Gemini down")
    fake_gemini.models.handler = handler
    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "React"})
        error = receive_until(ws, "error")[-1]
        assert error["code"] == "summary_failed"
        assert_closed(ws)
    assert backend.summary_posts == []


def test_interviewer_failure_sends_error(client, fake_gemini, backend):
    fake_gemini.models.handler = lambda schema, call: "not json"
    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        ws.receive_json()
        ws.send_json({"type": "text", "text": "React"})
        assert ws.receive_json()["code"] == "interview_failed"
        assert_closed(ws)


@pytest.mark.parametrize("status", [401, 404, 500])
def test_auth_failed(client, fake_gemini, backend, status):
    backend.config_status = status
    with client.websocket_connect("/ws/interview?token=itk_good&input=voice") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and msg["code"] == "auth_failed"
        assert_closed(ws)


@pytest.mark.parametrize("url", ["/ws/interview?token=itk_bad&input=text", "/ws/interview?input=text"])
def test_auth_failed_bad_or_missing_token(client, fake_gemini, backend, url):
    with client.websocket_connect(url) as ws:
        assert ws.receive_json()["code"] == "auth_failed"
        assert_closed(ws)


def test_backend_unreachable_is_auth_failed(client, fake_gemini, monkeypatch):
    import httpx

    def boom(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(interview, "BACKEND_TRANSPORT", httpx.MockTransport(boom))
    with client.websocket_connect("/ws/interview?token=itk_good&input=text") as ws:
        assert ws.receive_json()["code"] == "auth_failed"


def test_gemini_not_configured(client, no_gemini, backend):
    with client.websocket_connect("/ws/interview?token=itk_good&input=voice") as ws:
        assert ws.receive_json()["code"] == "gemini_not_configured"
        assert_closed(ws)


# ---------- voice mode ----------
def content(**kwargs):
    return types.LiveServerMessage(server_content=types.LiveServerContent(**kwargs))


def audio_turn(data: bytes):
    return types.Content(role="model", parts=[types.Part(inline_data=types.Blob(data=data, mime_type="audio/pcm;rate=24000"))])


def test_voice_mode_end_to_end(client, fake_gemini, backend):
    live = FakeLiveSession([
        # turn 1: the greeting (released by the kickoff prompt)
        [content(output_transcription=types.Transcription(text="Hey Ana! ")),
         content(model_turn=audio_turn(b"\x01\x02")),
         content(output_transcription=types.Transcription(text="What do you want to build?")),
         content(turn_complete=True)],
        # turn 2: the user answers, the interviewer replies and is interrupted
        [content(input_transcription=types.Transcription(text="I mostly")),
         content(input_transcription=types.Transcription(text=" do React")),
         content(output_transcription=types.Transcription(text="Nice, how")),
         content(interrupted=True),
         content(turn_complete=True)],
        # turn 3: goodbye, then the interviewer ends the interview
        [content(output_transcription=types.Transcription(text="Thanks, bye!")),
         content(turn_complete=True),
         types.LiveServerMessage(tool_call=types.LiveServerToolCall(
             function_calls=[types.FunctionCall(name="finish_interview", args={})]))],
    ])
    fake_gemini.aio.live.live = live
    fake_gemini.models.handler = lambda schema, call: SUMMARY

    with client.websocket_connect("/ws/interview?token=itk_good&input=voice") as ws:
        assert ws.receive_json()["type"] == "ready"
        turn1 = receive_until(ws, "turn_complete")
        assert turn1 == [
            {"type": "transcript", "role": "interviewer", "text": "Hey Ana! ", "final": False},
            {"type": "audio", "data": base64.b64encode(b"\x01\x02").decode()},
            {"type": "transcript", "role": "interviewer", "text": "What do you want to build?", "final": False},
            {"type": "transcript", "role": "interviewer", "text": "Hey Ana! What do you want to build?", "final": True},
            {"type": "turn_complete"},
        ]
        ws.send_json({"type": "audio", "data": base64.b64encode(b"\x10\x00" * 160).decode()})
        turn2 = receive_until(ws, "turn_complete")
        assert turn2 == [
            {"type": "transcript", "role": "user", "text": "I mostly", "final": False},
            {"type": "transcript", "role": "user", "text": " do React", "final": False},
            {"type": "transcript", "role": "user", "text": "I mostly do React", "final": True},
            {"type": "transcript", "role": "interviewer", "text": "Nice, how", "final": False},
            {"type": "transcript", "role": "interviewer", "text": "Nice, how", "final": True},
            {"type": "interrupted"},
            {"type": "turn_complete"},
        ]
        ws.send_json({"type": "audio", "data": base64.b64encode(b"\x00\x00").decode()})
        rest = receive_until(ws, "interview_complete")
        assert rest[-1] == {"type": "interview_complete", "summary_saved": True, "summary": SUMMARY["summary"]}
        assert_closed(ws)

    # Live session setup
    [connect] = fake_gemini.aio.live.connects
    assert connect["model"] == "gemini-3.1-flash-live-preview"
    config = connect["config"]
    assert config.response_modalities == [types.Modality.AUDIO]
    assert config.input_audio_transcription is not None and config.output_audio_transcription is not None
    assert "What role do you want?" in config.system_instruction and "finish_interview" in config.system_instruction
    assert "Hey Ana!" in live.client_content[0].parts[0].text
    first_audio = live.realtime[0]["audio"]
    assert first_audio.data == b"\x10\x00" * 160 and first_audio.mime_type == "audio/pcm;rate=16000"

    [posted] = backend.summary_posts
    assert posted["input_mode"] == "voice"
    assert [(t["role"], t["text"]) for t in posted["transcript"]] == [
        ("interviewer", "Hey Ana! What do you want to build?"),
        ("user", "I mostly do React"),
        ("interviewer", "Nice, how"),
        ("interviewer", "Thanks, bye!"),
    ]
    assert posted["traits"] == {"highlights": SUMMARY["traits"]}


def test_voice_mode_client_end_and_typed_text(client, fake_gemini, backend):
    live = FakeLiveSession([[content(output_transcription=types.Transcription(text="Hi Ana!")),
                             content(turn_complete=True)]])
    fake_gemini.aio.live.live = live
    fake_gemini.models.handler = lambda schema, call: SUMMARY

    with client.websocket_connect("/ws/interview?token=itk_good&input=voice") as ws:
        ws.receive_json()
        receive_until(ws, "turn_complete")
        ws.send_json({"type": "text", "text": "I'd rather type: I do design"})
        ws.send_json({"type": "end"})
        assert receive_until(ws, "interview_complete")[-1]["summary_saved"] is True

    assert live.realtime == [{"text": "I'd rather type: I do design"}]
    [posted] = backend.summary_posts
    assert ("user", "I'd rather type: I do design") in [(t["role"], t["text"]) for t in posted["transcript"]]


def test_voice_mode_time_limit(client, fake_gemini, backend, monkeypatch):
    monkeypatch.setattr(interview, "SECONDS_PER_MINUTE", 0.1)
    live = FakeLiveSession([[content(input_transcription=types.Transcription(text="I build robots")),
                             content(turn_complete=True)]])
    fake_gemini.aio.live.live = live
    fake_gemini.models.handler = lambda schema, call: SUMMARY

    with client.websocket_connect("/ws/interview?token=itk_good&input=voice") as ws:
        ws.receive_json()
        assert receive_until(ws, "interview_complete")[-1]["summary_saved"] is True
    assert backend.summary_posts[0]["transcript"][0]["text"] == "I build robots"
