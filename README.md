# SquadUp

Find teammates and groups for events like HackTX. Members join an event, get AI-ranked recommendations of people and open teams (Gemini), send requests, and form a team once both sides accept. Teams then get a chat and a video-call link.

| Folder | What it is | Port |
|---|---|---|
| `backend/` | FastAPI core API: auth, orgs, events, recommendations, requests, chat | 8001 |
| `agents/` | Gemini agents: Recommender, voice/text Interviewer, Summarizer | 8000 |
| `frontend/` | React + Vite web app | 5173 (dev) / 4173 (preview) |
| `deploy/` | Docker Compose + Caddy for a real server ([deploy/README.md](deploy/README.md)) | |
| `docs/CONTRACT.md` | The API contract between all three services | |
| `PLAN.md` | Plan, task status and open questions | |

## 1. Prerequisites
- [uv](https://docs.astral.sh/uv/) (Python), Node.js 20+, and git. On Windows, run the commands below in Git Bash.

## 2. Keys (never commit them)
The keys are **not** in GitHub. Ask a teammate for them privately (DM, in person or a password manager), then:

```bash
cp backend/.env.example backend/.env    # fill in the values below
cp agents/.env.example  agents/.env     # GEMINI_API_KEY and INTERNAL_API_KEY
```

| Variable (`backend/.env`) | Notes |
|---|---|
| `DATABASE_URL` | TigerData Postgres URL, including the password and `?sslmode=require`. Leave it as `REPLACE_ME` to use a local database instead (no setup needed). |
| `SESSION_SECRET` | Any long random string: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client |
| `GEMINI_API_KEY` | Also goes in `agents/.env` |
| `SNOWFLAKE_ACCOUNT`, `_USER`, `_PASSWORD`, `_WAREHOUSE`, `_DATABASE`, `_SCHEMA` | User `SQUADUP_APP` (role `SQUADUP_ROLE` by default). Leave `SNOWFLAKE_TABLE` empty: the app uses its own `SQUADUP_EMBEDDINGS` table. |
| `SERPAPI_API_KEY` | Note the name: `SERPAPI_API_KEY`, not `SERPAPI_KEY` |
| `INTERNAL_API_KEY` | Any long random string. **Must be the same** in `agents/.env`. |

Any service without a key falls back gracefully (pgvector instead of Snowflake, similarity order instead of Gemini, no social lookup), so the app still runs.

**Network note:** many campus and venue Wi-Fi networks block database ports (5432 and TigerData's port). If the backend can't reach TigerData, switch to a phone hotspot, or set `DATABASE_URL=REPLACE_ME` to use the local database.

## 3. Run it locally
Three terminals:

```bash
# 1. Backend
cd backend
uv run alembic upgrade head                  # creates/updates the tables (TigerData is already set up)
uv run python -m app.seed                    # demo data; safe to re-run. --reset wipes seed data and reseeds
APP_ENV=local DEV_LOGIN=1 uv run uvicorn app.main:app --port 8001

# 2. Agents
cd agents
uv run uvicorn main:app --port 8000

# 3. Frontend
cd frontend
npm ci
npm run dev                                  # http://localhost:5173
```

Locally, the login page has a dev-login picker for the seed users (Priya Sharma, Ana Ruiz, Morgan Reyes). Google sign-in also works: `http://localhost:5173/api/auth/google/callback` is registered.

## 4. Share a public demo link (no server needed)
This runs everything on your laptop and gives a public `https://….trycloudflare.com` link through a Cloudflare quick tunnel. The laptop must stay on and online.

```bash
# 1. Tunnel (download cloudflared from github.com/cloudflare/cloudflared/releases); note the https://….trycloudflare.com URL it prints
cloudflared tunnel --no-autoupdate --url http://localhost:4173

# 2. Backend in production mode, pointed at that URL (U = the tunnel URL)
U=https://YOUR-TUNNEL.trycloudflare.com
cd backend
APP_ENV=production DEV_LOGIN=0 FRONTEND_ORIGIN=$U OAUTH_REDIRECT_URL=$U/api/auth/google/callback \
  AGENTS_URL=http://localhost:8000 AGENTS_WS_URL=wss://${U#https://}/agents/ws/interview \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8001

# 3. Agents (as in section 3), then the built frontend
cd frontend && npm run build
__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=.trycloudflare.com npx vite preview --host 127.0.0.1 --port 4173 --strictPort
```

Then in Google Cloud Console, on the OAuth client, add `$U/api/auth/google/callback` as an authorized redirect URI and `$U` as an authorized JavaScript origin. The tunnel URL changes every time cloudflared restarts.

On the public link, sign-in is Google only (dev-login is off). The seeded "UT Austin" org auto-approves `@utexas.edu` accounts; anyone else can create their own org from the sidebar.

For an always-on deployment on a server, see [deploy/README.md](deploy/README.md).

## 5. Tests
```bash
cd backend  && uv run pytest
cd agents   && uv run pytest
cd frontend && npm test && npm run build && npm run lint
```
