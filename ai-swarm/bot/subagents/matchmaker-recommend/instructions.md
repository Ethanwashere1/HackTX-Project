# matchmaker-recommend

You critique the Recommender in `agents/` (`POST /recommend`).

## Product

Backend ranks by embedding similarity; agents rerank with reasons.
Demo needs reasons that cite shared topics or complementary skills.

## Check

1. Optional `traits` / `topic_signals` / `group_need` on viewer + candidates.
2. Prompt weighs topic overlap, complementary skills, shared group_need,
   working-style traits — not only profile_text.
3. Response IDs ⊆ request; scores clamped; limit honored.
4. Invalid/empty Gemini output → `recommender_failed` (backend falls back).
5. Reasons match event tone (casual vs professional).

## Deliver

Concrete prompt/test changes under `agents/`. Flag backend payload
enrichment gaps without editing backend.
