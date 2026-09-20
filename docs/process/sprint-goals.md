# Sprint goals

Source of truth: the sprint goal stories in Jira (GF-85, GF-64, GF-65, GF-66).
Keep this file in sync when a goal changes.

- **Sprint 0 — Setup & team agreements:** Definition of done, check-in cadence, PR review
  rules and board agreed; AWS preflight complete (Bedrock access approved, quotas recorded,
  judge deployment up); corpus and packet specs reviewed; architecture decisions skeleton
  drafted. No feature code.
- **Sprint 1 — Foundation:** AWS foundation, budget and CI in place; corpus ingested,
  chunked and indexed; extraction pipeline produces typed, redacted records with confidence;
  Postgres schema, repository module and seeds; all five rules pass boundary tests;
  golden set authored; `fieldsight submit` works end to end on a real packet.
- **Sprint 2 — Agent system & harness:** full LangGraph topology with Coordinator, three
  workers and Reviewer; P4 shows a Reviewer rejection + narrowed re-dispatch; Gateway/ECS
  tools live with entitlement checks; four-stage harness and escalation triggers enforced;
  sessions and bounds working; all CLI commands run against P1–P4; first judged eval run.
- **Sprint 3 — Hardening & delivery:** evaluators and CI eval gate complete; injection and
  entitlement-denial tests demonstrated; both services deployed through CI/CD; external MCP
  client demo; final judged eval with delta; architecture doc and evaluation report written;
  demo artifacts committed; live demo rehearsed to time.