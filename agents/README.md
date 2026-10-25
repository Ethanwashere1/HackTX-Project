# SquadUp agents service

Gemini agents for SquadUp: the **Interviewer** (Gemini Live voice, plus a text mode), the **Summarizer** and the **Recommender**. FastAPI on port 8000. Shapes follow `docs/CONTRACT.md` sections 8 and 9.

## Run
```bash
cd agents
uv sync
uv run uvicorn main:app --reload --port 8000
uv run pytest -q          # no network: Gemini and the backend are mocked
```
Docker: `docker build -t squadup-agents agents/ && docker run -p 8000:8000 --env-file agents/.env squadup-agents`

## Env
Read from the environment, `agents/api.env` and `agents/.env` (both gitignored; see `.env.example`). Empty or `REPLACE_ME` counts as unset.

| Name | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | none | The service boots without it; Gemini calls then return 503 `gemini_not_configured` (WebSocket: `error` with that code). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Interviewer (text), Summarizer, Recommender. |
| `GEMINI_LIVE_MODEL` | `gemini-3.1-flash-live-preview` | Voice Interviewer (Live API, audio-native). |
| `BACKEND_URL` | `http://localhost:8001` | For the `/internal/interviews/...` calls. |
| `INTERNAL_API_KEY` | none | Shared `X-Internal-Key` secret. If unset, internal endpoints reject every call. |

## Endpoints
- `GET /health` → `{"ok": true, "service": "agents"}`
- `POST /recommend` (`X-Internal-Key`): contract section 8. Reranks with optional `traits` / `topic_signals` / `group_need` on viewer and candidates. Only candidate IDs from the request come back (deduped, score clamped to 0..1, at most `limit`). Errors: 401 `unauthenticated`, 422 `validation_error`, 502 `recommender_failed`, 503 `gemini_not_configured`; the backend then uses similarity order.
- `POST /profile-overview` (`X-Internal-Key`): questionnaire answers + social notes + interview → `{overview, traits}` (topics, group_need, working style, …). Errors: 502 `overview_failed`, 503 `gemini_not_configured`.
- `POST /generate-questions` (`X-Internal-Key`): host QuizGen → `{questions: [{text, kind, options, required}]}`. Dedupes existing texts; choice kinds need ≥2 options. Errors: 502 `quizgen_failed`, 503 `gemini_not_configured`.
- `WS /ws/interview?token=…&input=voice|text`: contract section 9.
  - On connect it fetches `GET {BACKEND_URL}/internal/interviews/{token}/config`. Any failure there sends `error` `auth_failed` and closes.
  - Voice: browser PCM16 16 kHz in, 24 kHz `audio` out, plus `transcript`, `turn_complete` and `interrupted`. Transcripts stream as `final: false` chunks (append them), then one `final: true` message with the full utterance (it replaces the chunks).
  - Text: send `{"type":"text"}`; each reply is a `transcript` (interviewer, final) followed by `turn_complete`.
  - Ends on `{"type":"end"}`, when the interviewer finishes, or at `max_minutes`. The Summarizer then POSTs `{transcript, summary, traits: {"highlights": [...]}, input_mode}` to `/internal/interviews/{token}/summary`, and the server sends `interview_complete` (`summary_saved` is false if the POST failed; `summary` is null if the user never answered) and closes.
  - Other error codes: `bad_request`, `gemini_not_configured`, `interview_failed`, `summary_failed`.
- `POST /internal/interview-summary` (`X-Internal-Key`): `{transcript: str}` → `{summary, traits}`.
- `POST /api/interview-turn`: `{history: [...]}` → one Interviewer turn (legacy, no event config).
