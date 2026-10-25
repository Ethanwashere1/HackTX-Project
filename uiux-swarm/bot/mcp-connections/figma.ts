import { defineConnection } from "@grok/agent-sdk/connections";

// Figma Dev Mode MCP — authorize with: agent-sdk mcp oauth figma
export default defineConnection({
  url: "https://mcp.figma.com/mcp",
  oauth: true,
  advertiseTools: true,
  optional: true,
});
