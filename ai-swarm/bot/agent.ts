import { defineAgent } from "@grok/agent-sdk";

export default defineAgent({
  description:
    "SquadUp AI swarm coordinator: routes agents/ QA to interviewer, profiler, matchmaker, quizgen, and harness specialists, then merges a ship brief for product AI.",
  model: {
    id: "grok-4.5",
    params: [
      { id: "effort", value: "high" },
      { id: "fast", value: "true" },
    ],
  },
});
