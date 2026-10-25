# uiux-swarm

Agent SDK swarm for **SquadUp** UI/UX (HackTX). Five agents: one
coordinator plus four specialists (`visual-direction`,
`layout-composition`, `interaction-motion`, `a11y-critique`).

## Quick start

```bash
cd uiux-swarm
npx @grok/agent-sdk login   # once
npx @grok/agent-sdk validate --dir .
npx @grok/agent-sdk info --dir . --json
npx @grok/agent-sdk dev     # playground at http://127.0.0.1:3000/playground
```

## MCP connections

| Connection | Purpose | Setup |
| --- | --- | --- |
| `account` | Cursor account connectors | Host login / `CURSOR_API_KEY` |
| `playwright` | Demo-route visual QA | `npx` pulls `@playwright/mcp` |
| `figma` | Design tokens / frames / FigJam | Connect Figma in Cursor Settings → Tools & MCP (catalog client). CLI OAuth is blocked by Figma (403). |
| `axe` | Deque axe MCP scans | Optional: set `AXE_API_KEY`; else use `axe_checklist` tool + Playwright |
| `shadcn` | Component registry | `npx` pulls `shadcn` MCP |

All MCP files are `optional: true` so the project validates before
credentials exist.

## GitHub

`bot/channels/github.ts` wakes on pull_request webhooks and critiques
**`frontend/`** only. Set `GITHUB_WEBHOOK_SECRET` and `GITHUB_TOKEN`
(or a GitHub App) before live delivery. After `agent-sdk login`, you can
swap to `cursorAccount: { repos: ["Ethanwashere1/HackTX-Project"] }` for
Cursor-managed SCM events.

## Scope

Frontend UX only. Do not change `backend/` or `agents/` via this swarm.
