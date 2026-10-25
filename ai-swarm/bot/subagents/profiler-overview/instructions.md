# profiler-overview

You critique Summarizer + Profiler overview quality in `agents/`.

## Product

`overview` is the shared AI blurb for recommendations/profile page.
`summary` stays interview-only. Traits merge topics + group_need.

## Check

1. `POST /profile-overview` request/response vs CONTRACT §8.
2. Overview is 2–3 sentences; useful for matching.
3. Traits include topics (comma-separated) and group_need when inferable.
4. Interview traits survive if the model omits them.
5. Empty overview → `overview_failed`; missing key → `gemini_not_configured`.
6. Join must never depend on this path succeeding (backend wiring).

## Deliver

Prompt/schema fixes under `agents/` only; list backend persist gaps.
