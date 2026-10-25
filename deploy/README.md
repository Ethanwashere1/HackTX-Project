# Deploying SquadUp

One Vultr VM runs everything with Docker Compose:

| Service | What it does | Public? |
|---|---|---|
| `caddy` | HTTPS for `DOMAIN` (automatic Let's Encrypt), routing, static SPA | 80, 443 |
| `backend` | FastAPI on 8001; runs `alembic upgrade head` on every start | only `/api/*` |
| `agents` | Gemini agents on 8000 (`agents/Dockerfile`, owned by the agents team) | only `/agents/ws/*` → `/ws/interview` |
| `frontend` | one-shot: `npm ci && npm run build`, copies `dist/` into a volume for Caddy, then exits | via Caddy |

The database is TigerData (managed Postgres), not a container. Routing is in [Caddyfile](Caddyfile). Agents endpoints such as `/recommend` and `/internal/*` are only reachable inside the compose network.

## 1. Create the VM (Vultr)
1. **Deploy New Server:** Cloud Compute, a **US region** (Dallas is closest to Austin), image **Marketplace → Docker** on Ubuntu 24.04 (or plain Ubuntu 24.04, then install Docker in step 2), 2 vCPU / 4 GB is plenty. Add your SSH key.
2. **Firewall:** create a firewall group allowing inbound **TCP 22, 80, 443** (optionally UDP 443 for HTTP/3) and attach it to the server. Vultr's Ubuntu images also enable `ufw`, so run `ufw allow 80,443/tcp` on the server.
3. Note the server's public IPv4.

## 2. Install Docker if needed and clone the repo
```bash
ssh root@<server-ip>
docker compose version || (curl -fsSL https://get.docker.com | sh)
git clone -b <branch> https://github.com/Ethanwashere1/HackTX-Project.git squadup   # private repo: use a deploy key or a token
cd squadup
```
Use `Gemini_Agents` (or `main`, once merged) as the branch.

## 3. DNS (.tech domain)
At your .tech registrar, add an **A record** for the domain (`@`, or a subdomain) pointing to the server IPv4, with a short TTL. Check it with `dig +short <domain>` before starting Caddy. Caddy can only get a certificate once the domain resolves to this server and port 80 is reachable.

## 4. Google OAuth
In Google Cloud Console → APIs & Services → Credentials → your OAuth client:
- **Authorized redirect URI:** `https://<domain>/api/auth/google/callback`
- **Authorized JavaScript origin:** `https://<domain>`

## 5. Env files (never commit them)
```bash
cp deploy/.env.example deploy/.env          # set DOMAIN=<domain>
cp backend/.env.example backend/.env        # fill in the values below
touch agents/.env                           # must exist even if empty; fill in the values below
```
`docker-compose.yml` sets the production values for you, derived from `DOMAIN`: `APP_ENV=production`, `FRONTEND_ORIGIN`, `OAUTH_REDIRECT_URL`, `AGENTS_URL=http://agents:8000`, `AGENTS_WS_URL=wss://<domain>/agents/ws/interview` and `DEV_LOGIN=0` for the backend, plus `BACKEND_URL=http://backend:8001` for agents. They override the same names in the env files. You fill in:

**backend/.env**
- `SESSION_SECRET`: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. The backend won't start without it.
- `DATABASE_URL`: the TigerData connection string with `?sslmode=require`, copied from the TigerData console, e.g. `postgres://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require`. Without a real URL the backend exits with "DATABASE_URL is not set" (the image has no embedded Postgres). The first start creates the schema and the pgvector extension.
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- `GEMINI_API_KEY`
- `SNOWFLAKE_ACCOUNT`, `_USER`, `_PASSWORD`, `_WAREHOUSE`, `_DATABASE`, `_SCHEMA`, `_ROLE`
- `SERPAPI_API_KEY`
- `INTERNAL_API_KEY`: a random value. Use **the same value** in `agents/.env`.

**agents/.env:** `GEMINI_API_KEY`, `INTERNAL_API_KEY` (the same value as the backend), plus anything else the agents team documents.

Wrap any value that contains `$` in single quotes.

## 6. Start
```bash
cd deploy
docker compose up -d --build
docker compose ps                 # backend/agents should become "healthy"; frontend shows "exited (0)"
curl -I https://<domain>/         # the SPA
curl https://<domain>/api/me      # 401 JSON from the backend means routing works
```
**Before `frontend/` exists** (it needs `package.json`, `package-lock.json` and an `npm run build` that writes `dist/`), start the other services only: `docker compose up -d --build backend agents caddy`. Likewise, leave out `agents` until `agents/Dockerfile` exists.

## Logs, updates, demo reset
```bash
docker compose logs -f backend            # or agents / caddy / frontend
git pull && docker compose up -d --build  # update: rebuilds, re-runs migrations, rebuilds the SPA
docker compose up -d --build frontend     # rebuild the SPA only
docker compose up -d --force-recreate backend   # pick up backend/.env changes (restart alone doesn't)
docker compose exec backend python -m scripts.seed --reset   # demo reset: wipe and reseed
```
Don't delete the `squadup_caddy_data` volume: it holds the certificates, and reissuing too often hits Let's Encrypt rate limits.

## Troubleshooting
- **No certificate / TLS errors:** check `docker compose logs caddy`. DNS must point at this server and port 80 must be open.
- **Backend restarting:** check `docker compose logs backend` for a missing `SESSION_SECRET`, a missing `DATABASE_URL`, or a TigerData connection or SSL error.
- **Login loops or `redirect_uri_mismatch`:** the Google redirect URI must match `https://<domain>/api/auth/google/callback` exactly.
- **Mic not available:** the page must be opened over `https://<domain>`, not the IP.
