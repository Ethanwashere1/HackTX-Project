# ai-swarm

Agent SDK swarm for **SquadUp** product AI QA (HackTX). Five agents: one
coordinator plus specialists (`interviewer-qa`, `profiler-overview`,
`matchmaker-recommend`, `quizgen-questions`, `agents-harness`).

**Ownership:** runtime Gemini prompts and endpoints live in `agents/`.
This swarm runs tests, checks contract shapes, and critiques `agents/`
diffs. It does **not** replace the Python service and must not edit
`backend/` or `frontend/`.

See [docs/AI_SWARM.md](../docs/AI_SWARM.md).

## Quick start

```bash
cd ai-swarm
npx @grok/agent-sdk login   # once
npm install
npx @grok/agent-sdk validate --dir .
npx @grok/agent-sdk info --dir . --json
npx @grok/agent-sdk dev     # playground at http://127.0.0.1:3000/playground
# or
npx @grok/agent-sdk run --dir . --message "Smoke agents: health, pytest, contract shapes"
```

## Tools

| Tool | Purpose |
| --- | --- |
| `run_agents_tests` | `cd agents && uv run pytest -q` (mocked Gemini) |
| `check_contract_shapes` | Fixture POSTs for `/health`, `/recommend`, `/profile-overview`, `/generate-questions` |
| `save_ai_decision` | Lock a prompt/eval choice for the session |
| `get_ai_context` | Reload locked AI decisions |

## Subagents

| When | Delegate to |
| --- | --- |
| Voice/text interview, WS §9 | `interviewer-qa` |
| Interview summary + `/profile-overview` | `profiler-overview` |
| `/recommend` traits/topics/group_need | `matchmaker-recommend` |
| `/generate-questions` quality | `quizgen-questions` |
| Boot, pytest, Docker smoke | `agents-harness` |

## MCP connections

| Connection | Purpose | Setup |
| --- | --- | --- |
| `account` | Cursor account connectors | Host login / `CURSOR_API_KEY` |
| `playwright` | Optional interview-screen smoke via frontend | `npx` pulls `@playwright/mcp` |

All MCP files are `optional: true` so the project validates before
credentials exist.

## GitHub

`bot/channels/github.ts` wakes on pull_request webhooks and critiques
**`agents/`** only. Set `GITHUB_WEBHOOK_SECRET` and `GITHUB_TOKEN`
before live delivery.

## Demo fallbacks (must stay green)

| Feature | Fallback |
| --- | --- |
| `/recommend` | Backend similarity order |
| `/profile-overview` | Prior overview / null; join still succeeds |
| `/generate-questions` | 502 `agents_unavailable`; manual builder works |
| Interview voice | Text mode; stub returns `gemini_not_configured` without a key |
