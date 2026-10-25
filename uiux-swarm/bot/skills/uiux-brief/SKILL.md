---
description: Use when producing or refreshing a SquadUp screen/flow UI/UX brief from specialist output.
---

# SquadUp UI/UX brief

1. Call `get_design_context` for the target screen (and related routes).
2. Delegate to all four subagents that apply: `visual-direction`,
   `layout-composition`, `interaction-motion`, `a11y-critique`.
3. If Playwright is available, walk the live route (or mock) and note
   what is broken or unclear for the demo script.
4. If Figma is linked, align tokens and spacing to the file; otherwise
   propose a minimal token set.
5. If axe is available, scan the URL/HTML and fold must-fix items into
   the a11y section.
6. Prefer shadcn registry components when they fit forms, dialogs, and
   lists — do not invent a parallel kit.
7. Merge one brief (goal → visual → layout → interaction → a11y → build
   notes → open questions).
8. Call `save_design_decision` for each locked choice (tokens, layout
   pattern, primary CTA, motion).
