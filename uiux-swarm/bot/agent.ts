import { defineAgent } from "@grok/agent-sdk";

export default defineAgent({
  description:
    "SquadUp UI/UX swarm coordinator: routes design work to visual, layout, interaction, and a11y specialists, then merges a buildable frontend brief.",
  model: {
    id: "grok-4.5",
    params: [
      { id: "effort", value: "high" },
      { id: "fast", value: "true" },
    ],
  },
});
