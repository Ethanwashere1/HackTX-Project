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
    "Persist a locked AI prompt/eval decision for this session (feature, topic, decision, rationale). Call after specialists agree or the user confirms.",
  effect: "idempotent",
  inputSchema: z.object({
    feature: z
      .string()
      .describe(
        "AI surface, e.g. recommend, profile-overview, generate-questions, interview",
      ),
    topic: z
      .string()
      .describe("Decision topic, e.g. traits-weighting, overview-length, quiz-kinds"),
    decision: z.string().describe("The locked choice in one or two sentences."),
    rationale: z
      .string()
      .describe("Why this choice fits SquadUp matching and the demo."),
  }),
  async execute({ feature, topic, decision, rationale }, ctx) {
    const key = `${ctx.session.id}:ai:${feature}:${topic}`;
    const record: AiDecision = {
      feature,
      topic,
      decision,
      rationale,
      savedAt: new Date().toISOString(),
    };
    await ctx.host.kv.put(key, record);

    const indexKey = `${ctx.session.id}:ai:index`;
    const index = ((await ctx.host.kv.get(indexKey)) as string[] | null) ?? [];
    if (!index.includes(key)) {
      index.push(key);
      await ctx.host.kv.put(indexKey, index);
    }

    return { ok: true as const, key, record };
  },
});
