# SquadUp Plan
_Last updated: 2026-10-25 (HackTX weekend). **Pivoted to the new product spec.** AI feature pass: profile overview, quiz question generation, interview, enriched matching — product AI in `agents/`, plus an `ai-swarm/` for run/build/test (see [docs/AI_SWARM.md](docs/AI_SWARM.md))._

## Goal & demo script
**Goal:** a web app for finding teams and joining groups. Users sign in with OAuth and either host an event (hackathon, study group, social) or join one. SquadUp recommends people and groups to connect with, and explains each recommendation, in a professional or casual context. Groups only form when both sides agree, after a short chat or video call. Once formed, a group gets a team page with everyone's contact methods. Events live in a feed inside larger organizations (a university, a company).

**Event types:**
- **Structured:** the host sets group count, min/max group size, required profile info and questionnaire questions. Joiners get recommended people and groups, and form or join groups.
- **Informal:** no groups. Joiners get recommended individuals and add them as connections.

**Demo script (about 3 min):**
1. Sign in with Google and open the "UT Austin" org feed.
2. The host creates "HackTX team-up": structured, casual, 6 groups of 3–4, three questionnaire questions.
3. A volunteer joins, answers the questionnaire and adds a GitHub/Instagram handle (SerpAPI pulls public info).
4. The volunteer optionally does a ~60 s live voice interview with Gemini. The transcript and summary appear on their profile.
5. The volunteer sees their top recommendations, each with a Gemini reason, ranked by Snowflake similarity.
6. They send a request to a group and chat briefly (or start a video call). The group accepts, and the volunteer accepts too.
7. The team page appears with members' Discord, phone and in-app chat.
8. Quick switch to an informal "Study buddies" event, which shows 1:1 connection recommendations with no groups.
9. Close on the .tech URL.

## Stack & architecture
| Service | Tech | Port | Owner |
|---|---|---|---|
| `frontend/` | React + TypeScript (Vite) | 5173 | Frontend dev 1 + 2 (Copilot + Cursor and Grok agents) |
| `backend/` (core API) | Python FastAPI, SQLModel + Alembic, TigerData (PostgreSQL) | 8001 | Lead (+ Claude agents) |
| `agents/` (AI service) | Google ADK Python, Gemini + Live API | 8000 | Gemini dev |
| `ai-swarm/` | Agent SDK (run/build/test of `agents/`) | n/a | Lead scaffolds; Gemini + swarm own agents QA |
| `uiux-swarm/` | Agent SDK (frontend UX only) | n/a | Frontend / UX |
| Matching store | Snowflake (profile embeddings + vector similarity) | n/a | Lead (+ Claude agents) |
| Deploy | Vultr VM, Docker Compose, Caddy (HTTPS), .tech domain | 443 | Lead |

**Data boundaries:**
- **TigerData (Postgres) is the operational DB.** It holds users, sessions, orgs, events, questionnaires, answers, profiles, interview summaries, requests and consent, groups, chat threads and messages.
- **Snowflake is only the analytical/matching layer.** It ingests profile embeddings and runs vector similarity at query time. No chat, sessions or other real-time updates go through Snowflake.
- **Fallback:** if Snowflake is down or slow, the backend runs the same similarity query with pgvector in TigerData.

**Recommendation pipeline:**
1. A profile is saved or updated: questionnaire answers + SerpAPI social info + interview summary → agents `POST /profile-overview` refreshes the shared overview/traits.
2. The backend embeds the profile text (answers + socials + interview + overview) with the Gemini embeddings API, stores the vector in TigerData (pgvector), and syncs it to Snowflake.
3. `GET recommendations` runs a Snowflake similarity query for the top ~20 candidates in the same event. It excludes yourself, your current group-mates, and people or groups you've declined. Groups that are already full are excluded too.
4. The backend calls agents `POST /recommend` (with optional `traits` / `topic_signals` / `group_need`) to rerank to the top N, each with a reason that considers topic overlap and complementary working traits.
5. On agent failure or timeout, the user gets the similarity order without reasons (`ranked_by: "similarity"`).

**AI feature map (product AI = `agents/`; wiring = backend; UI = frontend):**
| User-facing need | Agents endpoint | Backend | Frontend |
|---|---|---|---|
| Profile overview | `POST /profile-overview` | store `overview`/`traits`; call after join/interview/socials | Profile page shows overview |
| Quiz/assessment questions | `POST /generate-questions` | `POST /api/question-suggestions` proxy | Create-event questionnaire "Suggest questions" |
| Live interview | `WS /ws/interview` + Summarizer → `/internal/.../summary` | interview token + internal config/summary | Interview screen (mic + text fallback) |
| Match / recommend | `POST /recommend` (enriched) | similarity + payload enrichment | Recommendations page |

**Who does what. Gemini and Claude agents do not overlap.**
- **Gemini agents run inside the product (`agents/`, Gemini dev owns all prompts and logic):**
  - **Interviewer:** optional live voice over WebSocket (Gemini Live) + text fallback.
  - **Summarizer:** transcript → interview summary + traits → POSTs to the backend.
  - **Profiler / Overview:** questionnaire + socials + interview → profile `overview` + merged traits.
  - **QuizGen:** event context → short questionnaire question drafts for the host.
  - **Recommender:** reranks candidates with reasons using traits, topic signals, and group need.
- **`ai-swarm/` (Agent SDK):** run/build/test orchestration for `agents/` only — pytest harness, contract-shape checks, prompt QA. Patterned on `uiux-swarm/`. See [docs/AI_SWARM.md](docs/AI_SWARM.md). Does not replace product AI.
- **Claude agents are development tools only (`backend/`):**
  - **planner:** maintains PLAN.md and docs/.
  - **builder:** writes backend code (including agents client wiring).
  - **reviewer:** reviews it.
  - **tester:** writes and runs backend tests.

  The backend covers OAuth, orgs, events, join, SerpAPI, embeddings/Snowflake, recommendations proxy, question-suggestions proxy, overview regeneration hooks, requests/consent, chat, calls, team pages, deploy.

  The Claude agents never write code in `agents/` or `frontend/`.
- **Frontend devs (`frontend/`):** all UI (including overview display and quiz-suggest UX), plus all frontend unit/regression tests. Backend tests stay with the Claude tester.

## Contract summary
See [docs/CONTRACT.md](docs/CONTRACT.md) (DRAFT v1.0-pre.5). It covers:
- the session-cookie auth flow and `GET /api/me/profile` (overview + interview summary)
- `/api` endpoints for orgs, events, joining, `POST /api/question-suggestions`, recommendations, requests, threads/chat/call and groups
- `/internal` interview config/summary; agents `POST /recommend`, `POST /profile-overview`, `POST /generate-questions`; interview WebSocket (§9)
- Swarm brief: [docs/AI_SWARM.md](docs/AI_SWARM.md)

## Milestones
- **M0 – Reset + skeletons:**
  - delete the old `backend/`
  - contract agreed
  - all three services boot with stub data
  - Google OAuth login works
  - DB schema and migrations run on TigerData
- **M1 – Demo slice (no interview):** structured event → join with questionnaire → embedding → Snowflake recommendations → Gemini reasons → request → mutual accept → group page. **Also:** QuizGen suggest-questions on create-event; profile overview from answers (+ socials when present).
- **M2 – Interview + connection:** live voice interview and summary feeding the profile overview; enriched recommend traits; in-app chat; video call link; informal events.
- **M2.5 – AI harness:** `ai-swarm/` scaffolded; agents pytest + contract-shape smoke green; optional live Gemini smoke when key present.
- **M3 – Orgs + socials:** org feed, creating events inside an org, SerpAPI social lookup (feeds overview regen), contact methods on the team page.
- **M4 – Polish + deploy:** Vultr + .tech domain + HTTPS (the mic requires it), seed data, demo reset script, two rehearsals.

## Tasks by owner

### Frontend (dev 1 / dev 2)
- [ ] **M0** (dev 1) Scaffold Vite React + TS app with router and a `/api` proxy to :8001. Routes: `/login`, `/orgs/:id`, `/events/new`, `/events/:id`, `/events/:id/join`, `/events/:id/recommendations`, `/requests`, `/threads/:id`, `/groups/:id` — done when `npm run dev` serves all routes (depends on: —)
- [ ] **M0** (dev 1) Typed API client from CONTRACT.md with a mock mode (`VITE_USE_MOCKS=1`) — done when every page renders from mock JSON (depends on: contract agreed)
- [ ] **M0** (dev 2) Login page plus "Sign in with Google", and an auth guard using `GET /api/me` — done when login round-trips against the backend (depends on: backend OAuth)
- [ ] **M1** (dev 1) Create-event form with these fields — done when it POSTs `/api/events` (depends on: API client):
  - type (structured or informal) and tone
  - group count, min/max size
  - questionnaire builder: questions plus required fields
- [ ] **M1** (dev 1) Questionnaire AI assist — done when "Suggest questions" calls `POST /api/question-suggestions`, inserts editable drafts into the builder, and the form still works if the call returns 502 (depends on: API client, backend question-suggestions)
- [ ] **M1** (dev 2) Join flow: questionnaire form plus social handles — done when POST join succeeds and redirects to recommendations (depends on: API client)
- [ ] **M1** (dev 2) Recommendations page: person and group cards with reasons and a "Request" button — done when it renders GET recommendations (depends on: API client)
- [ ] **M1** (dev 2) Profile page shows `overview` (preferred) and interview `summary`/traits from `GET /api/me/profile` — done when a joined user sees an overview after backend regen (depends on: backend profile endpoint + overview hook)
- [ ] **M1** (dev 1) Requests inbox (incoming/outgoing, accept/decline) and the group page — done when accept leads to the group page (depends on: requests endpoints)
- [ ] **M2** (dev 2) Live voice interview screen — done when a full interview runs against the agents service:
  - mic capture → PCM16 16 kHz over the WebSocket
  - playback of 24 kHz audio, stopped on `interrupted`
  - live transcript and an "I'm done" button
  - a "Type instead" fallback
- [ ] **M2** (dev 1) Chat thread view (polling `GET messages?after=`) plus a "Start video call" button that opens the Jitsi URL — done when two browsers can chat (depends on: threads endpoints)
- [ ] **M2** (dev 2) Informal event UI: connection recommendations and a connections list — done when two users can connect (depends on: backend informal events)
- [ ] **M3** (dev 1) Org feed, org join requests, admin screen (choose verification method, approve/decline requests, upload member list), and creating an event inside an org — done when a join request can be approved and the feed then lists the org's events (depends on: orgs endpoints)
- [ ] **M3** (dev 2) Profile/contact settings (Discord, phone, socials, visibility) and contact methods on the group page — done when non-members can't see contacts (depends on: backend profile)
- [ ] **M4** (both) Polish, mobile layout, loading and error states, a QR code for event links — done when the demo script runs without dev tools open
- [ ] **Each milestone** (both) Frontend unit and regression tests for the pages built in that milestone — done when the frontend test suite is green

### Gemini agents (Gemini dev) — product AI in `agents/` only
- [x] **M0** ADK service on :8000 with `/health`, `/recommend`, `/ws/interview` — done when the frontend and backend can call them (depends on: contract agreed). _Present in repo; expand per tasks below._
- [ ] **M1** Recommender agent (enriched): candidates + viewer `profile_text` / optional `traits` / `topic_signals` / `group_need` → top N with reasons that cite topic overlap or complementary traits; same IDs only — done when pytest covers enriched payload and seeded backend get valid reranks (depends on: contract v1.0-pre.5, backend seed)
- [ ] **M1** QuizGen agent: `POST /generate-questions` per CONTRACT — done when mocked pytest asserts kinds/options and no duplicate texts (depends on: contract v1.0-pre.5)
- [ ] **M1** Profiler / Overview agent: `POST /profile-overview` from answers + social_notes + interview summary/traits → `overview` + merged traits — done when mocked pytest returns contract shape (depends on: contract v1.0-pre.5)
- [ ] **M2** Interviewer agent on the Gemini Live API — done when a real voice interview works from the browser (depends on: backend interview-config, frontend interview screen):
  - fetches interview-config: host questions, tone, the user's profile so far
  - streams audio both ways and emits transcripts
- [ ] **M2** Text mode on the same socket (`input=text`) — done when a typed interview completes (depends on: Interviewer)
- [ ] **M2** Summarizer agent: transcript → summary + traits, POSTed to `/internal/.../summary` — done when the summary shows on the profile and overview regen runs (depends on: backend endpoint + overview hook)
- [ ] **M2.5** Agents test suite expanded for overview, quizgen, enriched recommend, interview WS (mocked Gemini) — done when `cd agents && uv run pytest -q` is green without a live key (depends on: M1 agent endpoints)
- [ ] **M4** Latency tuning, end-of-interview detection, reconnect handling — done when 3 back-to-back interviews succeed

### AI swarm (lead scaffolds; Gemini uses for QA) — `ai-swarm/`
- [ ] **M2.5** (lead / Cursor) Scaffold `ai-swarm/` from [docs/AI_SWARM.md](docs/AI_SWARM.md) mirroring `uiux-swarm/` — done when `agent-sdk validate` + smoke eval pass and README states write scope = `agents/` only (depends on: AI_SWARM.md)
- [ ] **M2.5** (swarm / Gemini) Wire tools: `run_agents_tests`, `check_contract_shapes` for `/recommend`, `/profile-overview`, `/generate-questions`, `/health` — done when a swarm run reports pytest + shape results (depends on: scaffold, M1 agent endpoints)
- [ ] **M2.5** (swarm) Subagents live: interviewer-qa, profiler-overview, matchmaker-recommend, quizgen-questions, agents-harness — done when coordinator delegates and returns one ship brief (depends on: scaffold)
- [ ] **M4** (swarm) Optional live Gemini smoke path when `GEMINI_API_KEY` set; GitHub channel critiques `agents/` PRs only — done when documented in ai-swarm README (depends on: key available)

### Core backend (lead + Claude agents)
- [x] **M0** (lead) Delete the old `backend/` (organizer-generates-teams design) — done when the directory is gone (depends on: —)
- [ ] **M0** (planner) Finalize CONTRACT.md with the frontend devs (Gemini dev has approved the agent sections); bump to v1.0 — done when the frontend devs approve (depends on: —)
- [x] **M0** (builder) New FastAPI skeleton on :8001 — done when the server boots against TigerData and `alembic upgrade head` succeeds (depends on: TigerData DB URL). _Done on the embedded Postgres + pgvector (pgserver); re-run `alembic upgrade head` once the TigerData URL arrives._
  - `/health`, error format, settings from env
  - SQLModel + Alembic on TigerData Postgres, with the pgvector extension
- [x] **M0** (builder) Google OAuth (authorization code flow with a state check), httpOnly session cookie, `GET /api/me`, logout — done when the frontend login round-trips (depends on: Google client ID). _Code-complete and tested against a mocked Google; not yet tried with real Google credentials or the frontend. Dev-only `POST /api/auth/dev-login` for local use._
- [x] **M0** (builder) Schema — done when migrations apply cleanly (on the embedded Postgres; plus InterviewToken and UserSession). Tables: User, ContactMethod, Org, OrgMember (role, status), OrgRosterEntry, Event (incl. `max_groups_per_user`), Question, EventMember (answers), Profile (summary, embedding), Group, GroupMember, Request, Thread, Message, Connection
- [x] **M1** (builder) Events create/get/join with host parameters, questionnaire validation and the required profile fields — done when create → join stores the answers (depends on: schema). _Also `POST /api/events/{id}/interview` (hashed 10-min token). Join builds `profile_text`; the embedding and SerpAPI steps are hooks in `app/services/profiles.py` for their own tasks. M0 review fixes applied in the same pass._
- [ ] **M1** (builder) Embeddings and Snowflake — done when a new joiner appears in Snowflake within seconds (depends on: Snowflake account):
  - embed the profile text with Gemini embeddings and store it in pgvector
  - sync it to a Snowflake table
- [ ] **M1** (builder) `GET /api/events/{id}/recommendations` — done when the user gets ranked people and open groups, and the fallbacks are tested (depends on: embeddings, agents stub):
  - Snowflake similarity, with exclusion rules and full groups removed
  - pgvector fallback
  - agents `/recommend` rerank with enriched `traits` / `topic_signals` / `group_need` when available, with a similarity-order fallback
  - `people[].summary` prefers profile `overview` over interview `summary`
- [ ] **M1** (builder) Profile overview wiring — done when join (and later interview/socials) stores overview asynchronously and tests cover agents failure without failing join (depends on: agents `/profile-overview`, schema `overview` column or equivalent):
  - `GET /api/me/profile` returns overview, summary, traits, contacts, socials
  - after join / interview-summary / social_notes update: call agents `POST /profile-overview`, persist overview + merged traits, then re-embed
- [ ] **M1** (builder) `POST /api/question-suggestions` — done when it proxies to agents `/generate-questions`, validates count/kinds, returns 502 `agents_unavailable` on timeout, and API tests pass (depends on: agents QuizGen)
- [ ] **M1** (builder) Requests and consent — done when no group ever exceeds max_size or group_count and no user exceeds the event's `max_groups_per_user`, including when two accepts arrive at once (depends on: schema):
  - `POST /api/requests` to a user or a group
  - accept/decline
  - a group forms or a member is added only after both sides accept
  - enforce max_size and group_count with a row lock
- [ ] **M1** (builder) `GET /api/groups/{id}` team page — done when it's tested for members vs non-members (depends on: requests):
  - members, roles and summaries (prefer overview)
  - contact methods shown only to members
- [ ] **M1** (builder) Seed script: an org, one structured and one informal event, and about 15 profiled users with embeddings + sample overviews/traits — done when recommendations work on seed data (depends on: embeddings, overview)
- [ ] **M2** (builder) Internal endpoints `interview-config` and `interview-summary`, plus the interview token — done when the agents service round-trips, overview regenerates, and profiles re-embed (depends on: schema, overview wiring)
- [ ] **M2** (builder) Threads and messages (created with each request and group), plus a call link (Jitsi room URL) — done when two users chat via polling (depends on: requests)
- [ ] **M2** (builder) Informal events: 1:1 connection requests and a connections list, no groups — done when tested (depends on: requests)
- [ ] **M3** (builder) Orgs — done when only approved members see the feed and only org admins can approve (depends on: schema):
  - create an org (creator becomes admin) and choose a verification method: `manual`, `email_domain`, or `roster`
  - join requests: `email_domain` and `roster` auto-approve on a match, otherwise the request waits for an admin; `manual` always waits
  - admins approve/decline requests and upload a roster (CSV of names and/or emails)
  - feed of upcoming events; creating events inside an org
- [ ] **M3** (builder) SerpAPI social lookup on join or profile update — done when a failed lookup still lets the user join and get recommendations (depends on: SerpAPI key):
  - optional and cached
  - manual handle entry as a fallback
  - the result feeds the profile text
- [ ] **Each milestone** (reviewer) Review the backend diff; (tester) API and invariant tests — done when the suite is green before the milestone is called done
- [ ] **M4** (lead + builder) Deploy on Vultr — done when the demo script runs on the public URL:
  - Docker Compose: backend, agents, frontend build, Caddy HTTPS
  - .tech domain, env and secrets, OAuth redirect URIs
  - demo reset script

## Risks
- **Live voice audio and latency** (PCM formats, mic permissions; HTTPS needed off localhost). Mitigation: text fallback from M2, and an early HTTPS deploy test.
- **Snowflake setup or latency in a live demo.** Mitigation: the pgvector fallback in TigerData behind the same interface, and a short query timeout.
- **SerpAPI rate limits or blocked profiles.** Mitigation: optional, cached, manual handles allowed, and matching never depends on it.
- **OAuth redirect URIs and cookies across domains on deploy.** Mitigation: serve frontend and API from the same origin through Caddy, and register the prod redirect URI early.
- **Consent race conditions** (two accepts filling the last slot). Mitigation: a row lock on the group, plus a tester invariant.
- **Privacy:** contact methods and social info are exposed only to accepted group members or connections.
- **Contract drift between the 3 groups.** CONTRACT.md is the single source of truth, and changes go through the planner with a changelog line.
- **Gemini key missing or agent timeouts in demo.** Mitigation: every AI path has a fallback (similarity-only recs, null overview, manual questionnaire, text interview / `gemini_not_configured`).
- **Overview regen races** (join + interview completing close together). Mitigation: last-write-wins on profile.overview; re-embed after each successful overview; never block join on agents.
- **ai-swarm scope creep into backend/frontend.** Mitigation: AI_SWARM.md write boundary = `agents/` only; Claude owns backend wiring.

## Open Questions
1. What is the submission deadline and judging time? (Assumed: 3 am Central on October 25, 2026. The plan is not time-boxed to it.)
2. Which OAuth provider: Google only, or GitHub too? (Assumed: Google only.)
3. How is org membership verified? **Decided:** users request to join an org and must be accepted. Each org picks its method: direct admin approval, email domain check, or matching against an uploaded member list.
4. For a group join request, who must accept from the group? (Assumed: any one current member, plus the requester.)
5. Is a Jitsi room link enough for video calls? (Assumed: yes, no API key needed.)
6. Chat transport: polling or WebSocket? (Assumed: polling every 2 s for the demo.)
7. Embeddings: Gemini embeddings API or Snowflake Cortex? (Assumed: Gemini embeddings, computed in the backend.)
8. Test database: local Postgres with pgvector or a TigerData test DB? (Docker isn't installed, so: an embedded Postgres via the `pgserver` pip package, or `TEST_DATABASE_URL` pointing at a TigerData test DB.)
9. Does the Gemini dev agree with `/recommend`, the interview WebSocket and the audio formats? **Yes.**
10. Can a user be in more than one group per event? **Decided:** one group per structured event by default; the host can raise it with the event's `max_groups_per_user` setting.
11. Credentials: real TigerData, Google OAuth, Gemini, Snowflake and SerpAPI values come later. Until then `backend/.env` holds placeholders.
12. Quiz/assessment question generation? **Decided (2026-10-25):** new agents `POST /generate-questions` + backend `POST /api/question-suggestions`; host still saves via create-event. Awaiting Gemini + frontend confirm on shapes in CONTRACT v1.0-pre.5.
13. Profile overview vs interview summary? **Decided:** keep interview `summary` separate; add AI `overview` from questionnaire + socials + interview. Recs/team page prefer overview.
14. Who scaffolds `ai-swarm/`? **Assumed:** lead or Cursor agent from docs/AI_SWARM.md; Gemini owns product code in `agents/` and uses the swarm for QA. Claude does not write `ai-swarm/` product prompts into `agents/`.
15. Do we need durable "prior engagement history" across events for matching? **Assumed for demo:** derive `topic_signals` / traits from the current profile + past event answers already stored for that user; no separate analytics store. Revisit post-demo if needed.
