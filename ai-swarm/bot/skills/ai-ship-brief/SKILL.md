---
description: Use when producing or refreshing a SquadUp agents/ AI ship brief from specialist output.
---

# SquadUp AI ship brief

1. Call `get_ai_context` for the target feature.
2. Call `run_agents_tests` and `check_contract_shapes` (or delegate
   `agents-harness` to do both).
3. Delegate to specialists that apply: `interviewer-qa`,
   `profiler-overview`, `matchmaker-recommend`, `quizgen-questions`.
4. Merge one brief (goal → harness → interview → overview → quiz → match
   → agents patches → wiring gaps → open questions).
5. Call `save_ai_decision` for each locked prompt/eval choice.
6. Never patch `backend/` or `frontend/` — list gaps for other owners.
