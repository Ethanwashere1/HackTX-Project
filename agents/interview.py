"""Interview WebSocket (CONTRACT.md section 9): the Interviewer over the Gemini Live API
(voice) or turn-by-turn (text), then the Summarizer, POSTed to the backend (section 8)."""
import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import WebSocket, WebSocketDisconnect
from google.genai import types

import agents
from agents import (
    GeminiNotConfigured,
    build_interviewer_instruction,
    env_value,
    get_client,
    run_gemini_interviewer,
    run_gemini_profiler,
)

log = logging.getLogger("squadup.interview")

BACKEND_TIMEOUT = httpx.Timeout(10.0)
GEMINI_CALL_TIMEOUT = 45.0  # seconds, per text turn or summary
SECONDS_PER_MINUTE = 60  # tests shrink this to exercise the time limit
BACKEND_TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests inject an httpx.MockTransport

FINISH_TOOL = types.Tool(function_declarations=[types.FunctionDeclaration(
    name="finish_interview",
    description="Ends the interview once you have enough information or the user wants to stop.",
)])


def backend_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=env_value("BACKEND_URL", "http://localhost:8001"),
        headers={"X-Internal-Key": env_value("INTERNAL_API_KEY", "")},
        timeout=BACKEND_TIMEOUT,
        transport=BACKEND_TRANSPORT,
    )


class AuthFailed(Exception):
    pass


async def fetch_config(token: str) -> dict:
    try:
        async with backend_client() as http:
            resp = await http.get(f"/internal/interviews/{quote(token, safe='')}/config")
    except httpx.HTTPError as exc:
        raise AuthFailed(f"Could not reach the backend ({exc.__class__.__name__})") from exc
    if resp.status_code in (401, 404):
        raise AuthFailed("Invalid interview token")
    if resp.status_code != 200:
        raise AuthFailed(f"Backend returned {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise AuthFailed("Backend returned an invalid config") from exc


async def post_summary(token: str, payload: dict) -> bool:
    try:
        async with backend_client() as http:
            resp = await http.post(f"/internal/interviews/{quote(token, safe='')}/summary", json=payload)
        return resp.status_code == 200
    except httpx.HTTPError:
        log.warning("Posting the interview summary failed", exc_info=True)
        return False


def build_greeting(config: dict) -> str:
    name = ((config.get("user") or {}).get("name") or "there").split()[0]
    event = config.get("event") or {}
    event_name = event.get("name") or "the event"
    if event.get("tone") == "professional":
        return f"Hi {name}, welcome to {event_name}. To start, what are you hoping to get out of this event?"
    return f"Hey {name}! Thanks for joining {event_name}. What are you hoping to build or find here?"


async def send_error(ws: WebSocket, code: str, message: str) -> None:
    """Sends an error message, then closes the socket (contract section 9)."""
    try:
        await ws.send_json({"type": "error", "code": code, "message": message})
        await ws.close()
    except Exception:
        pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class InterviewSession:
    def __init__(self, ws: WebSocket, token: str, config: dict, input_mode: str):
        self.ws = ws
        self.token = token
        self.config = config
        self.input_mode = input_mode
        self.transcript: list[dict] = []
        self.greeting = build_greeting(config)
        try:
            minutes = float(config.get("max_minutes") or 5)
        except (TypeError, ValueError):
            minutes = 5.0
        self.max_seconds = max(0.0, minutes) * SECONDS_PER_MINUTE
        # voice transcription arrives in chunks; buffered per role until the utterance ends
        self._buffers = {"user": "", "interviewer": ""}

    async def send(self, message: dict) -> None:
        await self.ws.send_json(message)

    async def fail(self, code: str, message: str) -> None:
        await send_error(self.ws, code, message)

    async def run(self) -> None:
        await self.send({"type": "ready", "greeting_text": self.greeting})
        try:
            async with asyncio.timeout(self.max_seconds) as deadline:
                if self.input_mode == "voice":
                    await self._converse_voice()
                else:
                    await self._converse_text()
        except WebSocketDisconnect:
            return  # the browser left without ending; nothing to save
        except TimeoutError:
            if not deadline.expired():
                log.warning("Interviewer timed out")
                return await self.fail("interview_failed", "The interviewer timed out")
            # time limit reached: finish normally
        except GeminiNotConfigured:
            return await self.fail("gemini_not_configured", "Gemini is not configured on the agents service")
        except Exception:
            log.exception("Interview failed")
            return await self.fail("interview_failed", "The interviewer failed")
        await self.finish()

    # ---------- text mode ----------
    async def _converse_text(self) -> None:
        self.transcript.append({"role": "interviewer", "text": self.greeting, "ts": _now()})
        while True:
            message = await self._receive_client()
            kind = message.get("type")
            if kind == "end":
                return
            if kind != "text" or not str(message.get("text", "")).strip():
                continue
            self.transcript.append({"role": "user", "text": str(message["text"]).strip(), "ts": _now()})
            turn = await asyncio.wait_for(
                asyncio.to_thread(run_gemini_interviewer, self.transcript, self.config), GEMINI_CALL_TIMEOUT
            )
            reply = turn["spoken_reply"]
            self.transcript.append({"role": "interviewer", "text": reply, "ts": _now()})
            await self.send({"type": "transcript", "role": "interviewer", "text": reply, "final": True})
            await self.send({"type": "turn_complete"})
            if turn["interview_complete"]:
                return

    async def _receive_client(self) -> dict:
        while True:
            try:
                message = json.loads(await self.ws.receive_text())
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                return message

    # ---------- voice mode ----------
    def live_config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=build_interviewer_instruction(self.config, voice=True),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=[FINISH_TOOL],
        )

    async def _converse_voice(self) -> None:
        client = get_client()
        async with client.aio.live.connect(model=agents.LIVE_MODEL_ID, config=self.live_config()) as session:
            name = (self.config.get("user") or {}).get("name") or "The user"
            await session.send_client_content(
                turns=types.Content(role="user", parts=[types.Part(
                    text=f"({name} just joined the interview. Open by saying: \"{self.greeting}\")"
                )]),
                turn_complete=True,
            )
            tasks = {asyncio.create_task(self._client_to_gemini(session)),
                     asyncio.create_task(self._gemini_to_client(session))}
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()  # re-raise a disconnect or Gemini error
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self._flush("user")
                await self._flush("interviewer")

    async def _client_to_gemini(self, session) -> None:
        while True:
            message = await self._receive_client()
            kind = message.get("type")
            if kind == "end":
                return
            if kind == "audio" and message.get("data"):
                try:
                    pcm = base64.b64decode(message["data"])
                except ValueError:
                    continue
                await session.send_realtime_input(audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
            elif kind == "text" and str(message.get("text", "")).strip():
                text = str(message["text"]).strip()
                self.transcript.append({"role": "user", "text": text, "ts": _now()})
                await session.send_realtime_input(text=text)

    async def _gemini_to_client(self, session) -> None:
        while True:
            received = 0
            async for msg in session.receive():  # one model turn per pass
                received += 1
                if msg.tool_call and any(fc.name == "finish_interview" for fc in msg.tool_call.function_calls or []):
                    return
                content = msg.server_content
                if not content:
                    continue
                if content.input_transcription and content.input_transcription.text:
                    await self._chunk("user", content.input_transcription.text)
                if content.output_transcription and content.output_transcription.text:
                    await self._flush("user")
                    await self._chunk("interviewer", content.output_transcription.text)
                if content.model_turn:
                    for part in content.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await self._flush("user")
                            await self.send({"type": "audio", "data": base64.b64encode(part.inline_data.data).decode()})
                if content.interrupted:
                    await self._flush("interviewer")
                    await self.send({"type": "interrupted"})
                if content.turn_complete:
                    await self._flush("user")
                    await self._flush("interviewer")
                    await self.send({"type": "turn_complete"})
            if received == 0:
                return  # Gemini closed the session

    async def _chunk(self, role: str, text: str) -> None:
        self._buffers[role] += text
        await self.send({"type": "transcript", "role": role, "text": text, "final": False})

    async def _flush(self, role: str) -> None:
        text = self._buffers[role].strip()
        self._buffers[role] = ""
        if text:
            self.transcript.append({"role": role, "text": text, "ts": _now()})
            await self.send({"type": "transcript", "role": role, "text": text, "final": True})

    # ---------- finish ----------
    async def finish(self) -> None:
        summary, saved = None, False
        if any(t["role"] == "user" for t in self.transcript):
            text = "\n".join(f"{t['role'].upper()}: {t['text']}" for t in self.transcript)
            try:
                profile = await asyncio.wait_for(asyncio.to_thread(run_gemini_profiler, text), GEMINI_CALL_TIMEOUT)
            except Exception:
                log.exception("Summarizer failed")
                return await self.fail("summary_failed", "Could not summarize the interview")
            summary = profile["summary"]
            saved = await post_summary(self.token, {
                "transcript": self.transcript,
                "summary": summary,
                "traits": {"highlights": profile["traits"]},
                "input_mode": self.input_mode,
            })
        try:
            await self.send({"type": "interview_complete", "summary_saved": saved, "summary": summary})
            await self.ws.close()
        except Exception:
            pass


async def run_interview(ws: WebSocket, token: str | None, input_mode: str) -> None:
    await ws.accept()
    if input_mode not in ("voice", "text"):
        return await send_error(ws, "bad_request", "input must be voice or text")
    if not token:
        return await send_error(ws, "auth_failed", "Missing interview token")
    try:
        config = await fetch_config(token)
    except AuthFailed as exc:
        return await send_error(ws, "auth_failed", str(exc))
    try:
        get_client()
    except GeminiNotConfigured:
        return await send_error(ws, "gemini_not_configured", "Gemini is not configured on the agents service")
    await InterviewSession(ws, token, config, input_mode).run()
