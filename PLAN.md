# SquadUp Plan
_Last updated: 2026-10-24 (HackTX weekend). **Pivoted to the new product spec.** The old organizer-generates-teams backend has been deleted; the new backend is being built from scratch._

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
| Matching store | Snowflake (profile embeddings + vector similarity) | n/a | Lead (+ Claude agents) |
| Deploy | Vultr VM, Docker Compose, Caddy (HTTPS), .tech domain | 443 | Lead |

**Data boundaries:**
- **TigerData (Postgres) is the operational DB.** It holds users, sessions, orgs, events, questionnaires, answers, profiles, interview summaries, requests and consent, groups, chat threads and messages.
- **Snowflake is only the analytical/matching layer.** It ingests profile embeddings and runs vector similarity at query time. No chat, sessions or other real-time updates go through Snowflake.
- **Fallback:** if Snowflake is down or slow, the backend runs the same similarity query with pgvector in TigerData.

**Recommendation pipeline:**
1. A profile is saved or updated: questionnaire answers + SerpAPI social info + interview summary.
2. The backend embeds the profile text with the Gemini embeddings API, stores the vector in TigerData (pgvector), and syncs it to Snowflake.
3. `GET recommendations` runs a Snowflake similarity query for the top ~20 candidates in the same event. It excludes yourself, your current group-mates, people or groups you've declined, and anyone with a pending request to or from you. Groups that are already full are excluded too.
4. The backend calls agents `POST /recommend` to rerank the candidates to the top N, each with a reason.
5. On agent failure or timeout, the user gets the similarity order without reasons (`ranked_by: "similarity"`).

**Who does what. Gemini and Claude agents do not overlap.**
- **Gemini agents run inside the product (`agents/`, Gemini dev owns all prompts and logic):**
  - **Interviewer:** the optional live voice interview over a WebSocket (Gemini Live), built from the host's questions and the event's tone. It also has a text fallback.
  - **Summarizer:** turns the transcript into a summary and traits and POSTs them to the backend.
  - **Recommender:** reranks the candidate list into the top N, with a reason for each.
- **Claude agents are development tools only (`backend/`):**
  - **planner:** maintains PLAN.md and docs/.
  - **builder:** writes backend code.
  - **reviewer:** reviews it.
  - **tester:** writes and runs backend tests.

  The backend covers:
  - Google OAuth and sessions
  - orgs, membership and the feed
  - events and questionnaires
  - joining and answers
  - SerpAPI social lookup
  - embeddings and the Snowflake sync and query, with the pgvector fallback
  - requests with mutual consent, and group formation
  - chat
  - video call links
  - team pages and contact-info privacy
  - deploy

  The Claude agents never write code in `agents/` or `frontend/`.
- **Frontend devs (`frontend/`):** all UI, plus all unit and regression testing of the web app (frontend). Backend tests stay with the Claude tester.

## Contract summary
See [docs/CONTRACT.md](docs/CONTRACT.md) (DRAFT v1.0-pre.7). It covers:
- the session-cookie auth flow
- `/api` endpoints for orgs, events, joining, recommendations, requests, threads/chat/call and groups
- `/internal` endpoints, `POST /recommend` and the interview WebSocket between the backend and agents

## Milestones
- **M0 – Reset + skeletons:**
  - delete the old `backend/`
  - contract agreed
  - all three services boot with stub data
  - Google OAuth login works
  - DB schema and migrations run on TigerData
- **M1 – Demo slice (no interview):** structured event → join with questionnaire → embedding → Snowflake recommendations → Gemini reasons → request → mutual accept → group page.
- **M2 – Interview + connection:** live voice interview and summary feeding the profile; in-app chat on requests and groups; video call link; informal events (1:1 connections).
- **M3 – Orgs + socials:** org feed, creating events inside an org, SerpAPI social lookup, contact methods on the team page.
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
- [ ] **M1** (dev 2) Join flow: questionnaire form plus social handles — done when POST join succeeds and redirects to recommendations (depends on: API client)
- [ ] **M1** (dev 2) Recommendations page: person and group cards with reasons and a "Request" button — done when it renders GET recommendations (depends on: API client)
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

### Gemini agents (Gemini dev)
- [ ] **M0** ADK service on :8000 with `/health`, a `/recommend` stub returning contract-shaped results, and a `/ws/interview` stub that echoes text — done when the frontend and backend can call all three (depends on: contract agreed)
- [ ] **M1** Recommender agent: candidates plus the viewer's profile and the event context → top N with reasons, same IDs only — done when the backend gets valid reranked results for the seeded users (depends on: backend seed)
- [ ] **M2** Interviewer agent on the Gemini Live API — done when a real voice interview works from the browser (depends on: backend interview-config, frontend interview screen):
  - fetches interview-config: host questions, tone, the user's profile so far
  - streams audio both ways and emits transcripts
- [ ] **M2** Text mode on the same socket (`input=text`) — done when a typed interview completes (depends on: Interviewer)
- [ ] **M2** Summarizer agent: transcript → summary + traits, POSTed to `/internal/.../interview-summary` — done when the summary shows on the profile and changes recommendations (depends on: backend endpoint)
- [ ] **M4** Latency tuning, end-of-interview detection, reconnect handling — done when 3 back-to-back interviews succeed

### Core backend (lead + Claude agents)
- [x] **M0** (lead) Delete the old `backend/` (organizer-generates-teams design) — done when the directory is gone (depends on: —)
- [ ] **M0** (planner) Finalize CONTRACT.md with the frontend devs (Gemini dev has approved the agent sections); bump to v1.0 — done when the frontend devs approve (depends on: —)
- [x] **M0** (builder) New FastAPI skeleton on :8001 — done when the server boots against TigerData and `alembic upgrade head` succeeds (depends on: TigerData DB URL). _Done on the embedded Postgres + pgvector (pgserver); re-run `alembic upgrade head` once the TigerData URL arrives._
  - `/health`, error format, settings from env
  - SQLModel + Alembic on TigerData Postgres, with the pgvector extension
- [x] **M0** (builder) Google OAuth (authorization code flow with a state check), httpOnly session cookie, `GET /api/me`, logout — done when the frontend login round-trips (depends on: Google client ID). _Code-complete and tested against a mocked Google; not yet tried with real Google credentials or the frontend. Dev-only `POST /api/auth/dev-login` for local use._
- [x] **M0** (builder) Schema — done when migrations apply cleanly (on the embedded Postgres; plus InterviewToken and UserSession). Tables: User, ContactMethod, Org, OrgMember (role, status), OrgRosterEntry, Event (incl. `max_groups_per_user`), Question, EventMember (answers), Profile (summary, embedding), Group, GroupMember, Request, Thread, Message, Connection
- [x] **M1** (builder) Events create/get/join with host parameters, questionnaire validation and the required profile fields — done when create → join stores the answers (depends on: schema). _Also `POST /api/events/{id}/interview` (hashed 10-min token). Join builds `profile_text`; the embedding and SerpAPI steps are hooks in `app/services/profiles.py` for their own tasks. M0 review fixes applied in the same pass._
- [x] **M1** (builder) Embeddings and Snowflake — done when a new joiner appears in Snowflake within seconds (depends on: Snowflake account). _Done with mocked tests only; the Snowflake vector SQL (`PARSE_JSON(...)::ARRAY::VECTOR(FLOAT,768)`, MERGE, `VECTOR_COSINE_SIMILARITY`) has not been run against real Snowflake._
  - embed the profile text with Gemini embeddings and store it in pgvector
  - sync it to a Snowflake table
- [x] **M1** (builder) `GET /api/events/{id}/recommendations` — done when the user gets ranked people and open groups, and the fallbacks are tested (depends on: embeddings, agents stub). _Done; fallback chain Snowflake → pgvector → agents rerank → similarity order._
  - Snowflake similarity, with exclusion rules and full groups removed
  - pgvector fallback
  - agents `/recommend` rerank, with a similarity-order fallback
- [x] **M1** (builder) Requests and consent — done when no group ever exceeds max_size or group_count and no user exceeds the event's `max_groups_per_user`, including when two accepts arrive at once (depends on: schema). _Done, with concurrency tests; crossing requests now resolve together (one group or connection)._
  - `POST /api/requests` to a user or a group
  - accept/decline
  - a group forms or a member is added only after both sides accept
  - enforce max_size and group_count with a row lock
- [x] **M1** (builder) `GET /api/groups/{id}` team page — done when it's tested for members vs non-members (depends on: requests). _Ticked from the code: `routers/groups.py` plus `tests/test_threads_groups.py` (members-only page, contacts never leak, rename, leave)._
  - members, roles and summaries
  - contact methods shown only to members
- [x] **M1** (builder) Seed script: an org, one structured and one informal event, and about 15 profiled users with embeddings — done when recommendations work on seed data (depends on: embeddings). _Done: `uv run python -m app.seed [--fake-embeddings|--reset|--wipe]`; also covers the M4 demo reset script._
- [x] **M2** (builder) Internal endpoints `interview-config` and `interview-summary`, plus the interview token — done when the agents service round-trips and the profile re-embeds (depends on: schema). _Done; token rules and limits in CONTRACT section 8. Traits shape is an open question (below)._
- [x] **M2** (builder) Threads and messages (created with each request and group), plus a call link (Jitsi room URL) — done when two users chat via polling (depends on: requests). _Ticked from the code: `routers/threads.py` plus `tests/test_threads_groups.py` (request-thread chat, stable call URL, group thread follows membership)._
- [x] **M2** (builder) Informal events: 1:1 connection requests and a connections list, no groups — done when tested (depends on: requests). _Done; connections list shape in CONTRACT section 7._
- [x] **M3** (builder) Orgs — done when only approved members see the feed and only org admins can approve (depends on: schema). _Done; builder-decided details (roster matching, feed window, PATCH semantics) in CONTRACT section 2._
  - create an org (creator becomes admin) and choose a verification method: `manual`, `email_domain`, or `roster`
  - join requests: `email_domain` and `roster` auto-approve on a match, otherwise the request waits for an admin; `manual` always waits
  - admins approve/decline requests and upload a roster (CSV of names and/or emails)
  - feed of upcoming events; creating events inside an org
- [x] **M3** (builder) SerpAPI social lookup on join or profile update — done when a failed lookup still lets the user join and get recommendations (depends on: SerpAPI key). _Done; not verified against real SerpAPI. `social_notes` is untrusted text that reaches the agents._
  - optional and cached
  - manual handle entry as a fallback
  - the result feeds the profile text
- [ ] **Each milestone** (reviewer) Review the backend diff; (tester) API and invariant tests — done when the suite is green before the milestone is called done
- [ ] **M4** (lead + builder) Deploy on Vultr — done when the demo script runs on the public URL:
  - Docker Compose: backend, agents, frontend build, Caddy HTTPS
  - .tech domain, env and secrets, OAuth redirect URIs
  - demo reset script (_done via `app.seed --reset`_)

## Risks
- **Live voice audio and latency** (PCM formats, mic permissions; HTTPS needed off localhost). Mitigation: text fallback from M2, and an early HTTPS deploy test.
- **Snowflake setup or latency in a live demo.** Mitigation: the pgvector fallback in TigerData behind the same interface, and a short query timeout.
- **SerpAPI rate limits or blocked profiles.** Mitigation: optional, cached, manual handles allowed, and matching never depends on it.
- **OAuth redirect URIs and cookies across domains on deploy.** Mitigation: serve frontend and API from the same origin through Caddy, and register the prod redirect URI early.
- **Consent race conditions** (two accepts filling the last slot). Mitigation: a row lock on the group, plus a tester invariant.
- **Privacy:** contact methods and social info are exposed only to accepted group members or connections.
- **Contract drift between the 3 groups.** CONTRACT.md is the single source of truth, and changes go through the planner with a changelog line.

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
12. **For the Gemini dev:** interview summary `traits` shape. CONTRACT section 8 shows flat traits (`{"working_style": …}`), but `agents/interview.py` sends `{"highlights": [...]}`. The backend accepts any JSON object, so both work today; which shape is canonical?
13. Recommendations: should people who have hit `max_groups_per_user`, or everyone once the event has `group_count` groups, be excluded? **Resolved: yes.** Recommendations now follow the accept rules. People at their group limit are excluded but stay reachable through their open group. There are no people once the event has `group_count` groups, and nothing at all once the viewer is at their own limit (CONTRACT section 4).
14. Org API proposals (frontend input wanted): return the auto-approved count from `PUT /roster`. (Done in CONTRACT v1.0-pre.7: `name` in the feed response and `GET /api/orgs/{org_id}`.)
