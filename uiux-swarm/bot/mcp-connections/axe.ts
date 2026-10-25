import { defineConnection } from "@grok/agent-sdk/connections";

// Deque axe MCP (commercial). Optional until AXE_API_KEY is set.
// Without a license, use the authored `axe_checklist` server tool + Playwright snapshots.
export default defineConnection({
  command: "npx",
  args: ["-y", "axe-mcp-server"],
  env: {
    AXE_API_KEY: "${AXE_API_KEY}",
  },
  advertiseTools: true,
  optional: true,
});
