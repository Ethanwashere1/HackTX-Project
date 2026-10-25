import { defineConnection } from "@grok/agent-sdk/connections";

/**
 * Figma MCP via Cursor account connectors.
 *
 * Figma's remote MCP (`https://mcp.figma.com/mcp`) only allows catalog
 * clients (Cursor IDE, VS Code, Claude Code, …). `agent-sdk mcp oauth`
 * is rejected with HTTP 403, so we do not OAuth from the CLI.
 *
 * Connect once in Cursor: Settings → Tools & MCP → Connect next to
 * Figma (or chat `/add-plugin figma`), then Allow access. This
 * connection forwards that authorized connector to the swarm.
 */
export default defineConnection({
  cursorAccount: true,
  servers: ["Figma"],
  advertiseTools: true,
  optional: true,
});
