# SquadUp API Contract — DRAFT v1.0-pre
_Status: draft, 2026-10-25, rewritten for the new product spec. Sections 8–9 (backend ↔ agents, interview WebSocket) are **approved by the Gemini dev**; sections 1–7 await the frontend devs. AI feature endpoints in §1 (`/api/me/profile`), §3 (`/api/question-suggestions`), and §8 (`/profile-overview`, `/generate-questions`, enriched `/recommend`) are **planner-proposed** — Gemini and frontend should confirm before calling M1/M2 done. Changes go through the planner and get a changelog line at the bottom._

## Conventions
- **Services:**
  - frontend: `http://localhost:5173` (Vite proxies `/api` to the backend, so the browser sees one origin)
  - backend: `http://localhost:8001`
  - agents (Gemini ADK): `http://localhost:8000`
  - In production, Caddy serves the frontend and `/api` on the same .tech origin, and the agents WebSocket at `/agents`.
- **JSON:** `snake_case` keys. IDs are opaque prefixed strings: `usr_`, `org_`, `evt_`, `q_`, `grp_`, `req_`, `thr_`, `msg_`, `con_`. Times are ISO 8601 UTC.
- **Errors:** every non-2xx response returns `{"error": {"code": "not_found", "message": "Event not found"}}`.
- **Auth:**
  - Google OAuth sets an httpOnly `session` cookie. All `/api` calls except auth and `/health` require it, and return 401 `unauthenticated` otherwise.
  - Backend ↔ agents calls send `X-Internal-Key: <shared secret>` (env `INTERNAL_API_KEY`).
- **Enums:**
  - event `type`: `structured | informal`
  - `tone`: `professional | casual`
  - question `kind`: `text | single_choice | multi_choice | number`
  - request `target_type`: `user | group`
  - request `status`: `pending | accepted | declined | cancelled | expired`
  - contact `kind`: `discord | phone | email | instagram | facebook | linkedin | github | other`

---

## 1. Auth
- **`GET /api/auth/google/login?next=/orgs`:** 302 redirect to Google with a `state` value.
- **`GET /api/auth/google/callback?code=…&state=…`:** checks `state`, creates or updates the user, sets the cookie, then 302 redirects to `next`.
- **`POST /api/auth/logout`:** returns 204.
- **`GET /api/me`:**
```json
{"user_id": "usr_a1", "name": "Ana Ruiz", "email": "ana@utexas.edu", "avatar_url": "…",
 "orgs": [{"org_id": "org_ut", "name": "UT Austin"}],
 "contacts": [{"kind": "discord", "value": "ana#1234"}]}
```
- **`GET /api/me/profile`:** the user's own shared profile, for their profile page. `summary` and `traits` are null until an interview summary is saved; `interviewed` is true once one is. The SerpAPI `social_notes` and the interview transcript are never returned.
```json
{"user_id": "usr_a1", "name": "Ana Ruiz", "email": "ana@utexas.edu",
 "summary": "Frontend dev who loves climate apps", "traits": {"ambition": "win"},
 "socials": [{"kind": "github", "value": "ana-ruiz"}],
 "contacts": [{"kind": "discord", "value": "ana#1234"}], "interviewed": true}
```
- **`PUT /api/me/contacts`:** body `{"contacts": [{"kind": "phone", "value": "+1…"}]}` (max 20, replaces the whole list). Returns 200 `{"contacts": [...]}`. Contacts are visible only to the user's group-mates and connections.
- **`GET /api/me/profile`:** the signed-in user's shared profile (one per person across events).
```json
{"user_id": "usr_a1", "name": "Ana Ruiz", "email": "ana@utexas.edu",
 "overview": "Frontend-leaning builder who wants a climate hack with a chill but ambitious team.",
 "summary": "Loves climate apps; prefers pairing; available all weekend.",
 "traits": {"working_style": "pairing", "ambition": "win", "topics": "climate,react",
            "group_need": "hackathon teammates"},
 "contacts": [{"kind": "discord", "value": "ana#1234"}],
 "socials": [{"kind": "github", "value": "ana-ruiz"}]}
```
  - `overview` is the AI-generated blurb from questionnaire answers + social notes + interview (null until generated).
  - `summary` is the interview-only summary (null if the user skipped the interview).
  - `traits` merges interview traits with overview traits (topics, group_need, working style, etc.).
  - Recommendations and team pages prefer `overview` when present, else `summary`.
- **Login errors:**
  - `/login` returns 503 `oauth_not_configured` while the Google credentials are unset.
  - On the callback, a missing, expired (10 min) or mismatched `state` returns 400 `invalid_oauth_state`; a missing `code` returns 400 `bad_request`; a Google token or profile failure (including a non-JSON response) returns 502 `oauth_failed`; an unverified Google email returns 403 `email_not_verified`.
  - An existing account is linked to a Google login by email only if it has no Google account yet. If the email already belongs to a different Google account (or a Google account's new email belongs to another user), the callback returns 409 `account_conflict` and nothing is overwritten.
  - If the user cancels at Google, the callback 302s to `/login?error=oauth_access_denied` on the frontend.
  - `next` must be a relative path (`/orgs`); anything else becomes `/`. The final redirect goes to `FRONTEND_ORIGIN` + `next`.
- **Dev only: `POST /api/auth/dev-login`** body `{"email": "ana@utexas.edu", "name": "Ana Ruiz"}`: signs in (creating the user if needed) without Google, sets the same `session` cookie and returns the `GET /api/me` body. It exists only when the backend has `DEV_LOGIN=1`, `APP_ENV` is `local`/`test` and `FRONTEND_ORIGIN` is localhost; otherwise it returns 404. Never available in a deployment; for local development and tests only.

## 2. Orgs and feed
Joining an org is always a request that must be approved. Each org picks one verification method:
- `manual`: an admin approves or declines every request.
- `email_domain`: auto-approved when the user's email domain is in `email_domains`; otherwise the request waits for an admin.
- `roster`: auto-approved only when the user's (Google-verified) email is on the uploaded member list; otherwise it waits for an admin. A name is never enough, since users choose their own display name: a user whose name matches a name-only row (a row without an email) waits, and the join-requests list shows `roster_match: "name"` as a hint for the admin.

Endpoints:
- **`GET /api/orgs`:** the user's orgs (with `my_role`: `admin | member`, and `my_status`: `pending | approved | declined`) plus discoverable orgs (`discoverable: true`).
```json
{"orgs": [{"org_id": "org_ut", "name": "UT Austin", "verification": "email_domain", "email_domains": ["utexas.edu"],
           "discoverable": true, "member_count": 312, "my_role": "member", "my_status": "approved"}]}
```
- **`GET /api/orgs/{org_id}`:** one org, the same object as an item of `GET /api/orgs`. Visible to any signed-in user when the org is discoverable or they have a membership row (any status); otherwise 404 `not_found`, the same as an unknown org, so hidden orgs can't be probed.
- **`POST /api/orgs`:** the creator becomes the org's first admin. `discoverable` (boolean, default `true`) controls whether non-members see the org in `GET /api/orgs`; a non-discoverable org is joined by link. `verification` defaults to `manual`.
```json
{"name": "UT Austin", "verification": "email_domain", "email_domains": ["utexas.edu"], "discoverable": true}
// 201 → {"org_id": "org_ut", "verification": "email_domain"}
```
  - `email_domains`: max 20, lowercased, a leading `@` is stripped. `email_domain` verification needs at least one domain, and a domain also matches its subdomains (`utexas.edu` matches `cs.utexas.edu`).
- **`PATCH /api/orgs/{org_id}`** (admin): change `name`, `verification`, `email_domains` or `discoverable`. Omitted or null fields stay unchanged. Pending requests that match after the change are auto-approved.
- **`POST /api/orgs/{org_id}/join`:** body `{"message": "CS junior"}` (optional). Returns `{"status": "approved" | "pending"}`. Returns 409 `already_member` if already approved. A user may ask again while pending or after a decline. A request made again after a decline always returns `pending` and waits for an admin, even on an email-domain or roster match, and a later settings change or roster upload doesn't auto-approve it either.
- **`GET /api/orgs/{org_id}/join-requests?status=pending`** (admin): `{"requests": [{"user_id": "usr_b2", "name": "Ben Li", "email": "ben@gmail.com", "message": "…", "requested_at": "…", "roster_match": "name"}]}`.
  - `roster_match`: `"email"` if the user's email is on the org's uploaded roster, `"name"` if only their name matches a roster row without an email (a hint, never auto-approved), else `null`.
- **`POST /api/orgs/{org_id}/join-requests/{user_id}/approve`** and **`/decline`** (admin): pending requests only, otherwise 409 `request_not_pending`. Returns `{"user_id": "usr_b2", "status": "approved" | "declined"}`.
- **`PUT /api/orgs/{org_id}/roster`** (admin): `multipart/form-data` with a `file` CSV that has `name` and/or `email` columns (max 1 MiB, 5000 data rows). It replaces the list and returns `{"entries": 312}`. Pending requests that now match are auto-approved. A header-only file clears the roster. Errors are 422 `invalid_roster`. The roster is never returned by the API.
- **`POST /api/orgs/{org_id}/admins`** (admin): `{"user_id": "usr_b2"}` makes an approved member an admin. Returns `{"user_id": "usr_b2", "role": "admin"}`, or 404 `not_found` if the user isn't an approved member.
- **`GET /api/orgs/{org_id}/feed`:** approved members only; anyone else, including for an unknown org, gets 403 `not_org_member`.
```json
{"org_id": "org_ut", "name": "UT Austin", "events": [{"event_id": "evt_h1", "name": "HackTX team-up", "type": "structured",
  "tone": "casual", "starts_at": "2026-10-25T15:00:00Z", "member_count": 42, "joined": false}]}
```
  - "Upcoming" means `starts_at` is null, in the future, or within the last 12 hours. Ordered by `starts_at`, nulls last; max 100 events.
  - Open proposal (PLAN.md Open Questions): return the auto-approved count from `PUT /roster`.

## 3. Events
**`POST /api/events`** (host)
```json
{"org_id": "org_ut", "name": "HackTX team-up", "description": "Find your hackathon team",
 "type": "structured", "tone": "casual",
 "group_count": 6, "min_size": 3, "max_size": 4, "max_groups_per_user": 1,
 "required_fields": ["skills", "experience_level"],
 "questions": [{"text": "What role do you want?", "kind": "single_choice",
                "options": ["frontend", "backend", "design", "ml"], "required": true},
               {"text": "What do you want to build?", "kind": "text", "required": false}],
 "interview_enabled": true, "starts_at": "2026-10-25T15:00:00Z"}
// 201 → {"event_id": "evt_h1", "share_url": "https://squadup.tech/events/evt_h1"}
```
- For `informal` events, `group_count`, `min_size`, `max_size` and `max_groups_per_user` are null; sending any of them returns 422 `validation_error`.
- Structured events require `group_count`, `min_size` and `max_size` (all ≥ 1, `min_size` ≤ `max_size`), else 422 `validation_error`.
- `max_groups_per_user` defaults to 1 for structured events. The host can raise it to let people join several groups.
- `required_fields` are snake_case keys (`^[a-z][a-z0-9_]{0,49}$`, max 20, unique). Up to 30 `questions`; `single_choice` and `multi_choice` need unique `options`, `text` and `number` take none. `required` defaults to false. `description` defaults to `""`, `interview_enabled` to false, `starts_at` to null.
- `org_id` is optional. Without it, the event is unlisted and reachable by link by any signed-in user. With it, only approved org members can create, see, join or interview for the event; anyone else (including for an unknown org) gets 403 `not_org_member`.
- `share_url` is `FRONTEND_ORIGIN/events/{event_id}`.

**`GET /api/events/{event_id}`** returns the event with `questions` (including their `question_id`s), `host`, `my_membership` (null, or `{joined_at, group_id}`) and `stats` (`member_count`, `groups_formed`):
```json
{"event_id": "evt_h1", "org_id": "org_ut", "name": "HackTX team-up", "description": "Find your hackathon team",
 "type": "structured", "tone": "casual", "group_count": 6, "min_size": 3, "max_size": 4, "max_groups_per_user": 1,
 "required_fields": ["skills", "experience_level"],
 "questions": [{"question_id": "q_1", "text": "What role do you want?", "kind": "single_choice",
                "options": ["frontend", "backend", "design", "ml"], "required": true},
               {"question_id": "q_2", "text": "What do you want to build?", "kind": "text", "options": null, "required": false}],
 "interview_enabled": true, "starts_at": "2026-10-25T15:00:00Z", "created_at": "2026-10-24T20:00:00Z",
 "share_url": "https://squadup.tech/events/evt_h1",
 "host": {"user_id": "usr_a1", "name": "Ana Ruiz"},
 "my_membership": {"joined_at": "2026-10-24T21:00:00Z", "group_id": null},
 "stats": {"member_count": 42, "groups_formed": 3}}
```
- `my_membership.group_id` is the user's earliest group in the event (an event with `max_groups_per_user` > 1 may have more).
- 404 `not_found` for an unknown event.

**`POST /api/events/{event_id}/join`**
```json
{"answers": [{"question_id": "q_1", "value": "frontend"}, {"question_id": "q_2", "value": "climate apps"}],
 "fields": {"skills": ["react", "figma"], "experience_level": "intermediate"},
 "socials": [{"kind": "github", "value": "ana-ruiz"}, {"kind": "instagram", "value": "@ana"}]}
// 201 → {"event_id": "evt_h1", "profile_status": "ready", "interview": {"available": true}}
```
- Returns 422 `invalid_answers` if a required question or field is missing, or if an answer or field is invalid:
  - answer values by question kind: `text` → string (max 2000), `single_choice` → one of the options, `multi_choice` → list of options, `number` → number. A null or empty answer counts as unanswered. Unknown or repeated `question_id`s are rejected.
  - `fields` may only contain the event's `required_fields`, and each must be non-empty: a string (max 500), number, boolean, or list of strings (max 50).
- `socials` use the contact `kind` enum (max 10); an unknown kind is 422 `validation_error`.
- Returns 409 `already_joined` if the user already joined.
- Joining stores the answers and creates or updates the user's profile, which is shared across events. `profile_status` is `ready` once the profile text is saved (the embedding follows asynchronously).
- SerpAPI lookup runs asynchronously and never blocks the join. Its result (`social_notes`) is untrusted text that reaches the agents via `profile_text` and the interview config (section 8).

**`POST /api/events/{event_id}/interview`** starts the optional interview:
```json
// 201
{"ws_url": "ws://localhost:8000/ws/interview", "interview_token": "itk_…", "expires_in": 600}
```
- Event members only: 403 `forbidden` before joining; 409 `interview_disabled` when the event has `interview_enabled: false`.
- Each call issues a new token, valid for `expires_in` seconds. The backend stores only its hash.

**`POST /api/question-suggestions`** (host AI assist for the questionnaire builder; session auth)
```json
{"name": "HackTX team-up", "type": "structured", "tone": "casual",
 "description": "Find your hackathon team",
 "existing_questions": [{"text": "What role do you want?", "kind": "single_choice",
                         "options": ["frontend", "backend", "design", "ml"]}],
 "count": 3, "hint": "availability and what they want to build"}
// 200
{"questions": [{"text": "How many hours can you commit this weekend?", "kind": "single_choice",
                "options": ["under 8", "8–16", "all weekend"], "required": true},
               {"text": "What do you want to build?", "kind": "text", "options": null, "required": false}]}
```
- The backend proxies to agents `POST /generate-questions` (section 8). It does **not** create an event; the host still POSTs `/api/events` with the chosen questions.
- `count` defaults to 3 (1–10). `existing_questions` and `hint` are optional. `name`/`type`/`tone` should match the create-event form so far.
- Returned questions use the same `kind` enum as create-event (`text | single_choice | multi_choice | number`). `single_choice` / `multi_choice` include `options`; `text` / `number` use `options: null`.
- On agents failure or timeout (10 s): 502 `agents_unavailable`. Frontend should keep the manual builder usable.

## 4. Recommendations
**`GET /api/events/{event_id}/recommendations?limit=10`** (members only)
```json
{"ranked_by": "gemini",
 "people": [{"user_id": "usr_b2", "name": "Ben Li",
             "summary": "Backend dev who wants to win; overlapping climate + API interests.",
             "score": 0.87, "reason": "You'd cover frontend and he covers backend; both want to ship a full demo."}],
 "groups": [{"group_id": "grp_1", "name": "Team Nebula", "size": 2, "max_size": 4,
             "members": [{"user_id": "usr_c3", "name": "Cara"}],
             "score": 0.81, "reason": "They're missing a designer and you listed Figma."}]}
```
- **Field values:**
  - `ranked_by` is `gemini`, or `similarity` when the agent rerank fails, in which case `reason` is null. It is also `similarity` when there are no candidates. With `ranked_by: "gemini"`, a list the agent returned nothing for is filled in similarity order with `reason: null`. Reasons are at most 300 characters.
  - In similarity mode, `score` is the cosine similarity rounded to 4 decimal places; a group member without a vector counts as 0.0.
  - `groups` is always `[]` for informal events.
  - `limit` is 1–50. Each candidate type (`people`, `groups`) returns at most `limit` entries. The `limit` sent to the agents' `/recommend` is `limit` × the number of candidate types present, capped at 50.
- **Excluded from results:** the viewer, people already in the viewer's groups, groups the viewer is in, full groups, users or groups the viewer declined or was declined by, and users or groups with a pending request to or from the viewer (or the viewer's groups).
- **Structured events only recommend what an accept could settle:**
  - People who already have `max_groups_per_user` groups are excluded; they stay reachable through their group while it's open.
  - `people` is `[]` once the event has `group_count` groups, or when `max_size` is below 2.
  - When the viewer has reached `max_groups_per_user`, both `people` and `groups` are `[]`, since either accept would fail with `group_limit_per_user`.
- The Socials line (handles) and the Public info line (SerpAPI notes) are stripped from each candidate's `profile_text`, including group members' texts, before it is sent to the agents.

## 5. Requests and consent
**`POST /api/requests`**
```json
{"event_id": "evt_h1", "target_type": "user", "target_id": "usr_b2", "message": "Want to team up?"}
// 201 → {"request_id": "req_9", "status": "pending", "thread_id": "thr_9"}
```
- A chat thread is created with each request so both sides can talk before agreeing.

**`GET /api/requests?box=incoming|outgoing&event_id=…`** lists requests, newest first. `incoming` holds requests to the user or to any of their groups (not their own); `outgoing` holds the ones they sent.
```json
{"requests": [{"request_id": "req_9", "event_id": "evt_h1",
  "sender": {"user_id": "usr_a1", "name": "Ana Ruiz"},
  "target_type": "user", "target": {"user_id": "usr_b2", "name": "Ben Li"},
  "direction": "outgoing", "other_party": {"type": "user", "id": "usr_b2", "name": "Ben Li"},
  "message": "Want to team up?", "status": "pending", "thread_id": "thr_9",
  "group_id": null, "connection_id": null,
  "created_at": "2026-10-24T21:00:00Z", "decided_at": null}]}
```
- `target` is `{"user_id", "name"}` for a `user` target and `{"group_id", "name"}` for a `group` target.
- `direction` echoes the box. `other_party` is the other side from the viewer: the target (`type` `user` or `group`) for an outgoing request, the sender (`type` `user`) for an incoming one.
- `group_id` / `connection_id` are the outcome of an accept, else null.

**`POST /api/requests/{request_id}/accept`** and **`/decline`**
- **Who can accept:**
  - For a `user` target, the target user.
  - For a `group` target, any current group member.
  - The requester's own request counts as their consent.
- **Result of accepting:**
  - Structured event, user → user: a new group forms with both users.
  - Structured event, user → group: the requester is added to the group.
  - Informal event: a connection is created.
  - **Resolved together:** accepting also accepts the other pending requests it makes unnecessary, with the same `group_id`/`connection_id` and `decided_by` = the acceptor:
    - the pair's crossing request (B → A when A → B is accepted), in both informal and structured events;
    - when someone joins a group, their pending user ↔ user requests with that group's current members.
  - A second accept on one of those requests then gets 409 `request_not_pending`.
  - Accepting a stale request between two people who already share a group or connection returns that existing group or connection instead of an error.
- **Errors:**
  - `group_full` (409): the group is already at max_size.
  - `group_limit_reached` (409): the event already has group_count groups.
  - `group_limit_per_user` (409): accepting would put either user in more groups than the event's `max_groups_per_user`.
  - `already_in_group` (409): the requester is already a member of the target group; also on `POST /api/requests` for a user target in a structured event when the two are already group-mates.
  - `already_connected` (409, `POST /api/requests`): informal event, the two are already connected.
  - `duplicate_request` (409, `POST /api/requests`): the sender already has a pending request to that target.
  - `request_not_pending` (409): the request was already accepted, declined, cancelled or expired.
- Accept response: `{"request_id": "req_9", "status": "accepted", "group_id": "grp_4" | null, "connection_id": "con_2" | null}`.

## 6. Threads, chat and calls
All thread endpoints are for participants only: 404 `not_found` for an unknown thread, 403 `forbidden` for a non-participant.
- **`GET /api/threads/{thread_id}`:** what the thread is about and who is in it.
```json
{"thread_id": "thr_9", "kind": "request", "title": "Ben Li", "event_id": "evt_h1",
 "group_id": null, "request_id": "req_9",
 "participants": [{"user_id": "usr_a1", "name": "Ana Ruiz"}, {"user_id": "usr_b2", "name": "Ben Li"}]}
```
  - `kind`: `group` (a group's own thread), `request` (the thread created with a request), or `connection` (in an informal event the connection keeps the accepted request's thread, so that thread then reports `connection`).
  - `title` is from the viewer's side: the group name for a `group` thread; for a `request` or `connection` thread, the other person's name, except that a user → group request shows the group name to its sender and the sender's name to the group's members.
  - `group_id`: the group for a `group` thread, the target group for a user → group request, else null. `request_id`: the request that created a `request` or `connection` thread, else null.
  - `participants` are the current participants, oldest first (people who left a group are removed).
- **`GET /api/threads/{thread_id}/messages?after=msg_…`:** `{"messages": [{"message_id": "msg_1", "sender_id": "usr_a1", "sender_name": "Ana Ruiz", "text": "Hi!", "sent_at": "…"}]}`, oldest first; `limit` 1–200 (default 100).
- **`POST /api/threads/{thread_id}/messages`:** `{"text": "Hi!"}` (1–4000 chars after trimming), returns 201 with the message object above, including `sender_name`.
- **`POST /api/threads/{thread_id}/call`:** returns `{"call_url": "https://meet.jit.si/squadup-thr9-x7k2"}`. The URL is stable per thread.

Each group has its own thread (`group.thread_id`). Clients poll about every 2 s.

## 7. Groups and connections
**`GET /api/groups/{group_id}`** (team page)
```json
{"group_id": "grp_4", "event_id": "evt_h1", "name": "Team Nebula", "thread_id": "thr_g4",
 "members": [{"user_id": "usr_a1", "name": "Ana Ruiz", "summary": "…",
              "contacts": [{"kind": "discord", "value": "ana#1234"}]}]}
```
Non-members get 403. Contacts are never returned to non-members anywhere in the API.

- **`PATCH /api/groups/{group_id}`:** members can rename the group with `{"name": "…"}`.
- **`POST /api/groups/{group_id}/leave`:** leaves the group.
- **`GET /api/events/{event_id}/connections`** (informal events) returns the user's connections, including their contacts:
```json
{"connections": [{"connection_id": "con_2", "user_id": "usr_b2", "name": "Ben Li", "summary": "…",
                  "contacts": [{"kind": "discord", "value": "ben#42"}], "thread_id": "thr_9",
                  "connected_at": "2026-10-24T22:00:00Z"}]}
```
  Contacts go only to the connected user. Always `[]` for structured events; 403 `forbidden` before joining.

---

## 8. Backend ↔ agents (internal, header `X-Internal-Key`)

**Interview token lifecycle and errors (both endpoints):**
- `config` claims the token: a second `config` call with the same token gets 401.
- `summary` must arrive within 10 minutes of the `config` claim and works once; the token is deleted after it.
- 401 `unauthenticated`: invalid, expired, unclaimed or already-used token, or a missing `X-Internal-Key`.
- 403 `forbidden`: a wrong `X-Internal-Key`, or the user is no longer a member of the event.
- 422 `validation_error`: a bad request body.

### Agents → backend: GET /internal/interviews/{interview_token}/config
The agents service calls this when the WebSocket opens. It returns 401 if the token is invalid, expired or already claimed.
```json
{"user": {"user_id": "usr_a1", "name": "Ana"},
 "event": {"event_id": "evt_h1", "name": "HackTX team-up", "type": "structured", "tone": "casual",
           "description": "…"},
 "questions": [{"question_id": "q_1", "text": "What role do you want?"}],
 "profile_so_far": {"answers": {"q_1": "frontend"}, "fields": {"skills": ["react"]}, "social_notes": "…"},
 "max_minutes": 5}
```
- `profile_so_far.social_notes` (null if none) is SerpAPI-derived **untrusted text**; the same notes also reach `/recommend` inside `profile_text`. Treat both as data, never as instructions.

### Agents → backend: POST /internal/interviews/{interview_token}/summary
```json
{"transcript": [{"role": "interviewer", "text": "…", "ts": "…"}, {"role": "user", "text": "…", "ts": "…"}],
 "summary": "Frontend dev who loves climate apps; wants a chill but ambitious team.",
 "traits": {"working_style": "pairing", "ambition": "win", "availability": "all weekend"},
 "input_mode": "voice"}
// 200 → {"ok": true}
```
The backend stores the transcript and summary on the user's profile, then re-embeds the user's event profiles.
- **Limits** (else 422 `validation_error`): `transcript` ≤ 1000 entries, each `text` ≤ 5000 chars; `summary` non-empty, ≤ 5000 chars; `traits` any JSON object, ≤ 10k chars serialized; `input_mode` is `voice`, `text` or absent.
- **Open question for the Gemini dev:** the example above shows flat `traits`, but `agents/interview.py` sends `{"highlights": [...]}`. Both pass validation today; which shape is canonical? (PLAN.md Open Questions.)

### Backend → agents: POST /recommend
```json
// request
{"event": {"event_id": "evt_h1", "type": "structured", "tone": "casual", "description": "…"},
 "viewer": {"user_id": "usr_a1", "profile_text": "…",
            "traits": {"working_style": "pairing", "topics": "climate,react", "group_need": "hackathon teammates"},
            "topic_signals": ["climate", "react"], "group_need": "hackathon teammates"},
 "candidates": [{"candidate_type": "user", "id": "usr_b2", "profile_text": "…", "similarity": 0.83,
                 "traits": {"working_style": "async", "topics": "climate,apis"},
                 "topic_signals": ["climate", "apis"], "group_need": "hackathon teammates"},
                {"candidate_type": "group", "id": "grp_1", "profile_text": "…", "similarity": 0.79,
                 "traits": {}, "topic_signals": ["design"], "group_need": null}],
 "limit": 10}
// 200
{"results": [{"candidate_type": "user", "id": "usr_b2", "score": 0.87, "reason": "…"}]}
```
- The response may only contain IDs from `candidates`.
- `traits`, `topic_signals`, and `group_need` are optional but preferred. The Recommender must weigh: overlapping topics / prior similar interests, complementary skills, shared `group_need`, and traits that suggest they work well together (working style, ambition, availability) — not only raw text similarity.
- Timeout is 20 s. On error, timeout or an invalid response, the backend returns the similarity order with `ranked_by: "similarity"`.

### GET /health (both services)
Returns `{"ok": true, "service": "agents" | "backend"}`.

---

## 9. Live interview WebSocket (browser ↔ agents)
`ws://localhost:8000/ws/interview?token=<interview_token>&input=voice|text`

**Data path:**
1. The browser streams mic audio to the agents service.
2. The Interviewer agent runs on the Gemini Live API and streams audio and transcripts back.
3. At the end, the Summarizer turns the transcript into a summary and POSTs it to the backend (section 8).

The browser never talks to Gemini directly, and the backend never handles audio.

**Client → server**
```json
{"type": "audio", "data": "<base64 PCM16 mono 16 kHz, ~100 ms chunks>"}
{"type": "text", "text": "I mostly do React"}
{"type": "end"}
```

**Server → client**
```json
{"type": "ready", "greeting_text": "Hey Ana! Tell me what you want to build."}
{"type": "audio", "data": "<base64 PCM16 mono 24 kHz>"}
{"type": "transcript", "role": "interviewer" | "user", "text": "…", "final": true}
{"type": "turn_complete"}
{"type": "interrupted"}
{"type": "interview_complete", "summary_saved": true, "summary": "…"}
{"type": "error", "code": "auth_failed", "message": "Invalid interview token"}
```
- `interrupted` means the user barged in, so the client should stop playback.
- The server closes the socket after `interview_complete` or `error`.

---

## Error codes
`unauthenticated` (401), `forbidden` (403), `not_org_member` (403), `not_org_admin` (403), `not_found` (404), `validation_error` (422), `invalid_answers` (422), `invalid_roster` (422), `already_joined` (409), `already_member` (409), `already_in_group` (409), `already_connected` (409), `duplicate_request` (409), `group_full` (409), `group_limit_reached` (409), `group_limit_per_user` (409), `request_not_pending` (409), `interview_disabled` (409), `internal_error` (500).
Auth and generic: `bad_request` (400), `invalid_oauth_state` (400), `email_not_verified` (403), `method_not_allowed` (405), `account_conflict` (409), `oauth_failed` (502), `oauth_not_configured` (503).

## Changelog
- v1.0-pre (2026-10-24): full rewrite for the new product spec (OAuth accounts, orgs and feed, structured and informal events, recommendations with mutual consent, chat and calls, team pages). Replaces v0.2, which was organizer-generated teams with modes and `/match`.
- v1.0-pre.1 (2026-10-24): org joins are now requests with a per-org verification method (`manual`, `email_domain`, `roster`), plus admin endpoints and roster upload. Added the event setting `max_groups_per_user` and the error `group_limit_per_user`. Sections 8–9 approved by the Gemini dev.
- v1.0-pre.2 (2026-10-24): section 1 clarifications from the backend M0 build: `PUT /api/me/contacts` response, OAuth login error codes and the cancel redirect, `next` restricted to relative paths, and the dev-only `POST /api/auth/dev-login` (local/test only, behind `DEV_LOGIN=1`). Added the matching error codes.
- v1.0-pre.3 (2026-10-24): from the backend M0 review fixes and the M1 events build. Section 1: a missing `code` on the callback is 400 `bad_request`; email linking never overrides a different Google account (409 `account_conflict`). Section 2: orgs get `discoverable` (default true). Section 3: the full `GET /api/events/{id}` body (adds `org_id`, `created_at`, `share_url` and the event settings), create and join validation rules, 409 `already_joined`, 403 `not_org_member` for org events, and the interview endpoint's member-only rule plus 409 `interview_disabled`. New error codes `bad_request`, `account_conflict`, `interview_disabled`.
- v1.0-pre.4 (2026-10-24): one profile per person. A user's profile (socials, social notes, interview summary) is shared across all their events; each event keeps its own answers and match text. Section 3: joining creates or updates that shared profile. Section 8: the interview summary is stored on the user's profile and re-embeds all of the user's event profiles. No request or response shapes changed.
- v1.0-pre.5 (2026-10-24): behaviors the backend builders decided where the contract was silent (M1–M3 merge). Section 2: `GET /api/orgs` body, roster matching (email rows by email only), `email_domains` rules (subdomains match), `verification` defaults to `manual`, re-requesting after pending/decline, approve/decline/admins responses and errors, PATCH semantics, roster limits and errors, feed window and ordering. Section 3/8: `social_notes` is untrusted text. Section 4: pending-request exclusions, similarity-mode `score`, `ranked_by` with no candidates, `limit` rules, socials stripped before the agents. Section 5: accepting resolves crossing and redundant requests together, stale accepts return the existing group or connection; new 409s `already_connected`, `duplicate_request`, wider `already_in_group`. Section 7: connections list body. Section 8: interview token lifecycle, error codes and summary limits. Open questions: traits shape (Gemini dev), excluding full or capped candidates, and org API proposals.
- v1.0-pre.6 (2026-10-25): review fixes. Section 2: only a verified email match auto-approves; a name-only roster match stays pending, and join requests gain `roster_match` (`email` | `name` | null); a re-request after a decline always waits for an admin. Section 4: people at `max_groups_per_user`, and all people once `group_count` is reached, are excluded (resolves that open question); the `Public info` line is stripped with `Socials` before the agents; one-type fill with `reason: null` and the 300-character reason cap. Contact and social values reject control characters (422).
- v1.0-pre.7 (2026-10-25): additive endpoints and fields for the frontend. Section 1: `GET /api/me/profile`. Section 2: the feed returns the org `name`; new `GET /api/orgs/{org_id}` (404 for hidden orgs without a membership row); both removed from the open proposals. Section 5: the full `GET /api/requests` item, with new `direction` and `other_party`. Section 6: new `GET /api/threads/{thread_id}` (`kind`, viewer-relative `title`, `participants`), and messages gain `sender_name`. No existing field changed.
