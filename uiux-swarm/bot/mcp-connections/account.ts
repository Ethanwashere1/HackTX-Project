import { defineConnection } from "@grok/agent-sdk/connections";

// Cursor account connectors (dashboard → MCP). Requires host login.
// optional so local validate works before credentials exist.
export default defineConnection({
  cursorAccount: true,
  advertiseTools: true,
  optional: true,
});
