# quizgen-questions

You critique QuizGen (`POST /generate-questions`) in `agents/`.

## Product

Hosts get AI-suggested assessment questions; they still save via
create-event. Backend proxies as `/api/question-suggestions`.

## Check

1. Kinds: `text | single_choice | multi_choice | number`.
2. Choice kinds have ≥2 unique options; text/number use `options: null`.
3. No duplicate of `existing_questions` text.
4. Count 1–10; prefer short texts fitting event tone.
5. Errors: `quizgen_failed`, `gemini_not_configured`, auth.

## Deliver

Agents patches + tests. Note frontend “Suggest questions” as wiring gap.
