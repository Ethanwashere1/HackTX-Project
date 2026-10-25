import { defineAgent } from "@grok/agent-sdk";

export default defineAgent({
  description:
    "Agents harness: boot agents/, run pytest, /health, contract-shape checks, optional Docker smoke. Use for run/build/test gates.",
});
