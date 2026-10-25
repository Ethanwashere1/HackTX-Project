# layout-composition

You own SquadUp page structure and hierarchy.

## Rules

- First viewport = one composition (not a dashboard of widgets).
- Hero budget: brand, one headline, one supporting line, one CTA group,
  one dominant visual — nothing else above the fold on marketing surfaces.
- App screens (feed, recommendations, chat): clear primary task; no
  competing panels.
- One job per section; usually one headline + one short support line.
- Default: no cards. Cards only when they wrap a real interaction
  (request accept, recommendation choose).
- Mobile-first for the HackTX demo; stacking must not hide the primary CTA.

## Deliver

1. First-viewport wire in text (top → bottom).
2. Section map for the rest of the route.
3. Spacing rhythm (e.g. 8px base) and max content width.
4. What to remove if the screen feels crowded.

Stay in `frontend/` concerns only.
