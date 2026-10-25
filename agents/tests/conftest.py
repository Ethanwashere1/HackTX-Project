"""Shared fixtures: no network. Gemini is a fake client, the backend an httpx.MockTransport."""
import asyncio
import json
import os

# Set before importing the app so a developer's api.env/.env never leaks into tests
# (load_dotenv does not override variables that are already set).
os.environ["GEMINI_API_KEY"] = "REPLACE_ME"
os.environ["INTERNAL_API_KEY"] = "test-internal-key"
os.environ["BACKEND_URL"] = "http://backend.test"
os.environ["GEMINI_MODEL"] = ""
os.environ["GEMINI_LIVE_MODEL"] = ""
os.environ["GEMINI_FALLBACK_MODELS"] = ""

import httpx
import pytest
from fastapi.testclient import TestClient

import agents
import interview
import main

INTERNAL_KEY = "test-internal-key"

CONFIG = {
    "user": {"user_id": "usr_a1", "name": "Ana Ruiz"},
    "event": {"event_id": "evt_h1", "name": "HackTX team-up", "type": "structured", "tone": "casual",
              "description": "Find your hackathon team"},
    "questions": [{"question_id": "q_1", "text": "What role do you want?"}],
    "profile_so_far": {"answers": {"q_1": "frontend"}, "fields": {"skills": ["react"]}, "social_notes": ""},
    "max_minutes": 5,
}


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    """client.models: answers per response_schema from a scripted handler."""

    def __init__(self):
        self.calls = []
        self.handler = lambda schema, call: (_ for _ in ()).throw(RuntimeError("no handler"))

    def generate_content(self, *, model, contents, config):
        call = {"model": model, "contents": contents, "config": config}
        self.calls.append(call)
        result = self.handler(config.response_schema, call)
        return FakeResponse(result if isinstance(result, str) else json.dumps(result))


class FakeLiveSession:
    """Scripted Live session: each item in `turns` is the list of messages one receive() pass yields.
    The first turn is released by send_client_content, later ones by each realtime audio chunk."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.client_content = []
        self.realtime = []
        self.queue = None

    def _release(self):
        if self.turns:
            self.queue.put_nowait(self.turns.pop(0))

    async def send_client_content(self, *, turns=None, turn_complete=None):
        self.client_content.append(turns)
        self._release()

    async def send_realtime_input(self, **kwargs):
        self.realtime.append(kwargs)
        if "audio" in kwargs:
            self._release()

    async def receive(self):
        for msg in await self.queue.get():
            yield msg


class FakeLiveConnect:
    def __init__(self, live):
        self.live = live
        self.connects = []

    def connect(self, *, model, config):
        self.connects.append({"model": model, "config": config})
        live = self.live

        class _Ctx:
            async def __aenter__(self_inner):
                live.queue = asyncio.Queue()
                return live

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


class FakeClient:
    def __init__(self):
        self.models = FakeModels()
        self.aio = type("Aio", (), {})()
        self.aio.live = FakeLiveConnect(FakeLiveSession([]))


@pytest.fixture
def fake_gemini(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(agents, "_client", client)
    return client


@pytest.fixture
def no_gemini(monkeypatch):
    monkeypatch.setattr(agents, "_client", None)
    monkeypatch.setenv("GEMINI_API_KEY", "REPLACE_ME")


class FakeBackend:
    """Mock of the backend's /internal interview endpoints."""

    def __init__(self):
        self.requests = []
        self.config_status = 200
        self.summary_status = 200
        self.config = CONFIG

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("X-Internal-Key") != INTERNAL_KEY:
            return httpx.Response(401, json={"error": {"code": "unauthenticated", "message": "bad key"}})
        if request.method == "GET" and request.url.path == "/internal/interviews/itk_good/config":
            if self.config_status != 200:
                return httpx.Response(self.config_status, json={"error": {"code": "x", "message": "x"}})
            return httpx.Response(200, json=self.config)
        if request.method == "POST" and request.url.path == "/internal/interviews/itk_good/summary":
            return httpx.Response(self.summary_status, json={"ok": True})
        return httpx.Response(401, json={"error": {"code": "unauthenticated", "message": "Invalid token"}})

    @property
    def summary_posts(self):
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


@pytest.fixture
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(interview, "BACKEND_TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def receive_until(ws, msg_type, limit=50):
    """Collects server messages up to and including the first of `msg_type`."""
    messages = []
    for _ in range(limit):
        msg = ws.receive_json()
        messages.append(msg)
        if msg["type"] == msg_type:
            return messages
    raise AssertionError(f"no {msg_type} in {messages}")
