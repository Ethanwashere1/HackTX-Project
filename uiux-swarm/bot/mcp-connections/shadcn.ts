import { defineConnection } from "@grok/agent-sdk/connections";

// shadcn/ui registry browse + install helpers.
export default defineConnection({
  command: "npx",
  args: ["-y", "shadcn@latest", "mcp"],
  advertiseTools: true,
  optional: true,
});
