# Demo / dummy data (removable)

This folder holds **frontend-only seed data** used when `VITE_USE_MOCKS=1` (the default for local demos).

## How to remove for database deploy

1. Set `VITE_USE_MOCKS=0` in the deploy environment (see `frontend/.env.example`).
2. Optionally delete this entire `src/demo/` directory and drop the `../demo` imports from `src/api/client.ts` — the live `/api/*` paths already talk to the backend + DB.
3. SerpAPI enrichment still goes through `GET /api/enrichment/*` (server-side key). Demo fallbacks live in `backend/app/services/serpapi.py` when `SERPAPI_API_KEY` is unset.

Do **not** ship secrets in this folder. Dummy handles and places are fake campus fixtures only.
