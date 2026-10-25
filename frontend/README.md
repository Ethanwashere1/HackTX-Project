# SquadUp frontend

React + TypeScript + Vite UI for SquadUp, implemented from the HackTX Figma file and `PLAN.md` / `docs/CONTRACT.md`.

## Run

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. By default the app talks to the real backend (start it from `backend/` with
`APP_ENV=local DEV_LOGIN=1 uv run uvicorn app.main:app --port 8001`, after `uv run alembic upgrade head`
and `uv run python -m app.seed --fake-embeddings`). Under `npm run dev` the login page shows a dev-login
picker for the seed users (Priya Sharma, Ana Ruiz, Morgan Reyes).

To run without a backend, set `VITE_USE_MOCKS=1` (only the exact value `1` enables the in-browser mocks
in `src/api/mocks.ts`).

Demo path: dev login → UT Austin feed → HackTX event → join → interview → recommendations → request/chat → team page.

## API

- Proxies `/api` → `http://localhost:8001`
- The interview connects to the `ws_url` returned by `POST /api/events/{id}/interview` (contract section 9).
- `src/api/types.ts` mirrors `docs/CONTRACT.md`; errors are thrown as `ApiError` with the contract's `error.code`.
