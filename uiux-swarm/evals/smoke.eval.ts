import { defineEval } from "@grok/agent-sdk/evals";

export default defineEval({
  tags: ["smoke"],
  description:
    "Persists a design decision with save_design_decision when asked to lock a choice.",
  async test(t) {
    await t.send(
      'Lock this design decision using the save_design_decision tool: screen "/login", topic "primary-cta", decision "Single Google sign-in button as the only CTA above the fold", rationale "Demo script starts with Google OAuth; competing CTAs slow the 3-minute path."',
    );
    t.succeeded();
    t.calledTool("save_design_decision");
  },
});
