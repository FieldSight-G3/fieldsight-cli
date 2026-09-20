# Working agreement

## Board
- Jira project G3-FieldSight (key GF). Every story has acceptance criteria before it enters a sprint.
- A card moves to Done only when it meets the [definition of done](definition-of-done.md).

## Daily check-in
- 6:00 AM PT on Teams.
- Format: did / doing / blocked.
- A blocker raised at check-in gets an owner before the call ends.

## Branching and PRs
- Branch names: `dev/GF-###-short-name` (e.g. `dev/GF-49-rules-engine`).
- Flow: branch → PR → 1+ reviewer approves → merge. No direct pushes to `main` (branch protection on).
- Include the Jira key in the PR title so the card links automatically.
- Reviews happen within one working day. If a PR waits longer, raise it at check-in.

## Lanes
- **A: Data.** Repository, seeds, ingestion, retrieval.
- **B: Core.** Rules engine, harness, escalation, CLI.
- **C: Agents & infra.** Graph, workers, tools, API, AgentCore, CI/CD.

Lanes set default ownership, not boundaries. Anyone can pick up work in another lane when it's blocking a sprint goal.