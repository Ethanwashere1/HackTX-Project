import { defineEval } from "@grok/agent-sdk/evals";

export default defineEval({
  tags: ["smoke"],
  description:
    "Persists an AI decision with save_ai_decision when asked to lock a choice.",
  async test(t) {
    await t.send(
      'Lock this AI decision using the save_ai_decision tool: feature "recommend", topic "traits-weighting", decision "Weigh overlapping topic_signals and shared group_need ahead of raw profile_text similarity", rationale "Demo script needs reasons that cite shared interests and complementary skills."',
    );
    t.succeeded();
    t.calledTool("save_ai_decision");
  },
});
