import { defineTool } from "@grok/agent-sdk/tools";
import * as z from "zod/v4";

type DesignDecision = {
  screen: string;
  topic: string;
  decision: string;
  rationale: string;
  savedAt: string;
};

export default defineTool({
  description:
    "Load previously saved UI/UX design decisions for this session. Optionally filter by screen route.",
  effect: "read",
  inputSchema: z.object({
    screen: z
      .string()
      .optional()
      .describe("If set, only return decisions for this route/surface."),
  }),
  async execute({ screen }, ctx) {
    const indexKey = `${ctx.session.id}:design:index`;
    const index = ((await ctx.host.kv.get(indexKey)) as string[] | null) ?? [];
    const decisions: DesignDecision[] = [];

    for (const key of index) {
      const record = (await ctx.host.kv.get(key)) as DesignDecision | null;
      if (!record) continue;
      if (screen && record.screen !== screen) continue;
      decisions.push(record);
    }

    return {
      ok: true as const,
      count: decisions.length,
      decisions,
    };
  },
});
