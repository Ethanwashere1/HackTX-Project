# ai-swarm — run / build / test for SquadUp product AI

_Status: scaffolded (2026-10-25) under `ai-swarm/` mirroring `uiux-swarm/`. This doc is the build brief; do not put product Gemini logic here — that stays in `agents/`._

## Decision

| Layer | Where | Who |
|---|---|---|
| **Product AI** (Interviewer, Summarizer/Overview, Recommender, QuizGen) | `agents/` (Google ADK + Gemini, port 8000) | Gemini dev |
| **Backend wiring** (proxies, profile storage, recommend payload enrichment) | `backend/` | Claude builder / tester |
| **UI that calls AI-backed APIs** | `frontend/` | Frontend devs |
| **Run / build / test swarm** | `ai-swarm/` (Agent SDK, like `uiux-swarm/`) | Lead or Cursor agent scaffolds; Gemini + swarm own agents QA |

**Do not** put runtime Gemini prompts in `ai-swarm/`. The swarm critiques, runs tests, and proposes patches under `agents/` (and only documents backend/frontend contract gaps — it never edits `backend/` or `frontend/` unless a follow-up explicitly reassigns ownership).

Claude planner/builder/reviewer/tester still **must not** write `agents/` or `frontend/`.

## Why a swarm (and not only pytest)

`agents/` already has pytest with mocked Gemini. That stays the CI gate. The swarm adds:

1. Contract-shape checks against `docs/CONTRACT.md` §8–9
2. Prompt / reason quality critique (overview, quiz questions, recommend reasons)
3. Live-path smoke when `GEMINI_API_KEY` is set (optional)
4. GitHub PR wakeups that review **`agents/`** diffs only (mirror of uiux-swarm → `frontend/`)

## Recommended layout (mirror `uiux-swarm/`)

```
ai-swarm/
  package.json                 # @grok/agent-sdk
  AGENTS.md
  README.md
  evals/
    evals.config.ts
    smoke.eval.ts              # validate + info + "agents health brief"
  bot/
    agent.ts                   # coordinator
    instructions.md
    channels/github.ts         # PRs touching agents/ only
    hooks/memory.ts
    mcp-connections/
      account.ts               # optional
      playwright.ts            # optional: interview screen smoke via frontend
    tools/
      run_agents_tests.ts      # `cd agents && uv run pytest -q`
      check_contract_shapes.ts # curl/fixture checks for /recommend, /profile-overview, /generate-questions
      save_ai_decision.ts      # lock prompt/eval choices for the session
      get_ai_context.ts
    subagents/
      interviewer-qa/          # Live + text interview quality, WS contract §9
      profiler-overview/       # interview summary + POST /profile-overview
      matchmaker-recommend/    # /recommend traits, topics, group_need, reasons
      quizgen-questions/       # /generate-questions quality + kind/options validity
      agents-harness/          # boot, health, pytest, Dockerfile smoke
```

## Subagents (always delegate)

| When | Delegate to |
|---|---|
| Voice/text interview, WS messages, barge-in, end detection | `interviewer-qa` |
| Interview summary, profile overview from answers+socials+interview | `profiler-overview` |
| Rerank quality, complementary skills, topic overlap, reasons | `matchmaker-recommend` |
| Host questionnaire suggestions, question kinds/options | `quizgen-questions` |
| `uv sync`, pytest, `/health`, Docker build of `agents/` | `agents-harness` |

Coordinator merges one **ship brief**: what to change under `agents/`, which contract gaps to flag to the planner, and which backend/frontend wiring tasks are blocked.

## Quick start (once scaffolded)

```bash
cd ai-swarm
npx @grok/agent-sdk login   # once
npx @grok/agent-sdk validate --dir .
npx @grok/agent-sdk info --dir . --json
npx @grok/agent-sdk dev     # playground
# or
npx @grok/agent-sdk run --dir . --message "Smoke agents: health, pytest, contract shapes"
```

## Scope boundaries

- **In scope:** `agents/**`, `docs/CONTRACT.md` AI sections (read-only critique), `agents/tests/**`
- **Out of scope for writes:** `backend/`, `frontend/`, `uiux-swarm/`
- **Backend/frontend gaps:** list them in the brief for Claude builder / frontend; do not patch those trees from this swarm

## Demo fallbacks the swarm must keep green

| Feature | Fallback when Gemini/key missing |
|---|---|
| `/recommend` | Backend returns similarity order (`ranked_by: "similarity"`) |
| `/profile-overview` | Prior overview kept / null; join still succeeds |
| `/generate-questions` | 502 `agents_unavailable`; manual builder works |
| Interview voice | Text mode on same WS; stub without key returns `gemini_not_configured` |

## Scaffold task acceptance

Done when:

1. `ai-swarm/` validates with Agent SDK (`validate` + `info --json`)
2. Coordinator instructions match this doc
3. `agents-harness` can run `uv run pytest -q` in `agents/` (mocked, no network)
4. Smoke eval passes
5. README states ownership: product AI in `agents/`, swarm is QA/orchestration only
