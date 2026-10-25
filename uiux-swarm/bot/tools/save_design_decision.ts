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
    "Persist a locked UI/UX design decision for this session (screen, topic, decision, rationale). Call after specialists agree or the user confirms.",
  effect: "idempotent",
  inputSchema: z.object({
    screen: z
      .string()
      .describe("Route or surface, e.g. /events/:id/recommendations"),
    topic: z
      .string()
      .describe("Decision topic, e.g. color-tokens, hero-layout, motion"),
    decision: z.string().describe("The locked choice in one or two sentences."),
    rationale: z.string().describe("Why this choice fits SquadUp and the demo."),
  }),
  async execute({ screen, topic, decision, rationale }, ctx) {
    const key = `${ctx.session.id}:design:${screen}:${topic}`;
    const record: DesignDecision = {
      screen,
      topic,
      decision,
      rationale,
      savedAt: new Date().toISOString(),
    };
    await ctx.host.kv.put(key, record);

    const indexKey = `${ctx.session.id}:design:index`;
    const index = ((await ctx.host.kv.get(indexKey)) as string[] | null) ?? [];
    if (!index.includes(key)) {
      index.push(key);
      await ctx.host.kv.put(indexKey, index);
    }

    return { ok: true as const, key, record };
  },
});
