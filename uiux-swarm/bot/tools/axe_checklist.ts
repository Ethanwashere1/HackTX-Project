import { defineTool } from "@grok/agent-sdk/tools";
import * as z from "zod/v4";

export default defineTool({
  description:
    "Return a SquadUp accessibility checklist and severity rubric for a screen. Pair with Playwright page snapshots (or Deque axe MCP when AXE_API_KEY is set).",
  effect: "read",
  inputSchema: z.object({
    screen: z.string().describe("Route or surface under review"),
    notes: z.string().optional().describe("Optional context from a live snapshot or PR diff"),
  }),
  async execute({ screen, notes }) {
    return {
      screen,
      notes: notes ?? null,
      mustCheck: [
        "Keyboard-only path for primary CTA and forms",
        "Visible focus rings on interactive controls",
        "Labels tied to inputs; errors associated with fields",
        "Contrast of text/accent over atmospheric backgrounds",
        "Live region for interview transcript and new chat messages",
        "Respect prefers-reduced-motion for decorative motion",
        "Touch targets ≥44px on mobile accept/decline/Request",
        "Mic permission denial and HTTPS requirement messaging",
      ],
      severityRubric: {
        blocker:
          "Cannot complete the demo script without mouse or sighted user",
        shouldFix:
          "Fails contrast/label/focus in a common path",
        nit: "Polish that does not block the 3-minute demo",
      },
      nextStep:
        "If Playwright is available, open the route and confirm each mustCheck against the accessibility snapshot. Report ship/fix/kill.",
    };
  },
});
