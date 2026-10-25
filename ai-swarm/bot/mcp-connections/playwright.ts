import { defineConnection } from "@grok/agent-sdk/connections";

// Browser visual QA for SquadUp demo routes.
export default defineConnection({
  command: "npx",
  args: ["-y", "@playwright/mcp@latest", "--headless"],
  advertiseTools: true,
  optional: true,
});
