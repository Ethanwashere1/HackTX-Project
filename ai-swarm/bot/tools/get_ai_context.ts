import { defineTool } from "@grok/agent-sdk/tools";
import * as z from "zod/v4";

type AiDecision = {
  feature: string;
  topic: string;
  decision: string;
  rationale: string;
  savedAt: string;
};

export default defineTool({
  description:
    "Load previously saved AI decisions for this session. Optionally filter by feature (recommend, profile-overview, etc.).",
  effect: "read",
  inputSchema: z.object({
    feature: z
      .string()
      .optional()
      .describe("If set, only return decisions for this AI surface."),
  }),
  async execute({ feature }, ctx) {
    const indexKey = `${ctx.session.id}:ai:index`;
    const index = ((await ctx.host.kv.get(indexKey)) as string[] | null) ?? [];
    const decisions: AiDecision[] = [];

    for (const key of index) {
      const record = (await ctx.host.kv.get(key)) as AiDecision | null;
      if (!record) continue;
      if (feature && record.feature !== feature) continue;
      decisions.push(record);
    }

    return {
      ok: true as const,
      count: decisions.length,
      decisions,
    };
  },
});
