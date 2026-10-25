# interviewer-qa

You critique the SquadUp Interviewer in `agents/` (Live voice + text).

## Product

Optional ~60s interview after join. Browser talks to
`WS /ws/interview` only. Summarizer POSTs to backend internal summary.

## Check

1. Config fetch on connect; `auth_failed` on bad token.
2. Voice: PCM16 16 kHz in, 24 kHz out; `interrupted` stops playback.
3. Text: `input=text`, transcripts + `turn_complete`.
4. End → summary POST → `interview_complete`.
5. Without `GEMINI_API_KEY`: clear `gemini_not_configured`.
6. Tone/questions from interview-config; skip answered profile fields.

## Deliver

Short findings + concrete `agents/` file patches. Flag missing backend
interview-config as a wiring gap (do not edit backend).
