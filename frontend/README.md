# SquadUp frontend

React + TypeScript + Vite UI for SquadUp, implemented from the HackTX Figma file and `PLAN.md` / `docs/CONTRACT.md`.

## Run

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — mocks are on by default (`VITE_USE_MOCKS=1`).

Demo path: **Continue with Google** → UT Austin feed → HackTX event → join → interview → recommendations → request/chat → team page.

## API

- Proxies `/api` → `http://localhost:8001`
- Set `VITE_USE_MOCKS=0` to hit the real backend
