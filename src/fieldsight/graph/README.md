# Graph

## Chart

```
{analyst_id, incident, tasks}                                    parent state (not built)
      |
COORDINATOR (not built) --dispatch--> <worker>_specialist_node   nodes/supervision.py
                                          |  invoke {task, incident}, recursion_limit from config
                                          v
                                    agent <-> tools              specialists.py (build_specialist)
                                          |  the model stops asking for tools,
                                          |  or MAX_SPECIALIST_TOOL_ROUNDS is spent
                                          v
                                    {"dossier": {worker: DossierLeg}}   the transcript stays behind
      |
reviewer_node --invoke on thread {analyst_id}:{incident_id}:reviewer-->  agent <-> tools (submit_review)
      |                                                                  nodes/review.py
      |  {"reviews": [verdict], "review_iterations": n + 1, "tasks": {worker: narrowed goal}}
      v
route_after_review --rejected, n < max_review_iterations--> "coordinator"
                   --approved, no verdict, or out of iterations--> "eligibility_check" (not built)
```

## Files

| File | Contains |
|---|---|
| `graph/specialists.py` | `SpecialistState`, `MAX_SPECIALIST_TOOL_ROUNDS`, and `build_specialist(name, brief, tools, checkpointer=None)`, which builds any `agent <-> tools -> END` loop. `SPECIALIST_BRIEFS` and `_TOOLSETS` hold what makes each worker different; `get_specialists` builds the three workers once. |
| `graph/nodes/supervision.py` | `_run_specialist`, which invokes a worker and maps its result back as its dossier leg, and the one-line dispatch nodes for Recordability, Reportability and Hazard Control. |
| `graph/nodes/review.py` | `postgres_checkpointer`, `get_reviewer` (the factory with the Reviewer's brief, tools and checkpointer), `reviewer_node` and `route_after_review`. |
| `types/dossier.py` | `DossierLeg` (task, proposal, decisions, cited) and `Dossier`, keyed by worker. |
| `schemas/rule_proposal.py` | The `Proposal` base, `ClassificationProposal`, `ReportingProposal`, `HazardControlProposal`, and the `Exclusion` and `ControlType` vocabularies. |
| `schemas/review.py` | `Rejection` (worker, quoted claim, problem, narrowed goal) and `ReviewVerdict`. |
| `tools/tools.py` | The `@tool` functions and each participant's tool list. |
| `rules/proposal_review.py` | `review_classification`, `review_reporting` and `review_hazard_control`, and `CONTROL_PARAGRAPHS`. |
| `prompts.py` | Each worker's brief and default goal, and the Reviewer's brief. |
| `config.py` | `max_review_iterations` (3) and `graph_recursion_limit` (25). |

Paths are relative to `src/fieldsight/`.

## Decisions

| Decision | Why |
|---|---|
| A specialist is data (a brief and a tool list) built by one factory, like the trainer's `specialists.py` | Spec section 5 defines each worker only by its goal, corpus, rules and tools |
| The model decides when it's done; `MAX_SPECIALIST_TOOL_ROUNDS` (10) caps it; an accepted proposal doesn't force an end | Section 5: a worker loops "until it stops requesting tools" |
| Tools per worker follow section 9; the `propose_*` tools are the structured output, validated at the tool boundary | Section 9: every propose tool takes a typed proposal and returns it validated or rejected |
| Tools read the incident from injected state, never from a model argument | Section 9: the model chooses what, never whose |
| Hazard Control's citation gate is two checks: the schema needs `control_type` and `provision`, and `review_hazard_control` needs the first chunk to be a `CFR-269-` chunk and the provision to sit in the control's paragraph of (l) | Section 5: a proposal with no resolving citation is rejected at the tool boundary |
| `ControlType` is a `Literal`, one value per paragraph (l)(1) to (l)(12) | A vocabulary defined in code, taken from the corpus text |
| A dossier leg holds the task, proposal, decisions and cited chunk text, never messages | Section 5: the Reviewer sees only structured outputs; the cited text lets it reject a claim its chunk doesn't state (P4) |
| The Reviewer is the same factory with its own brief and tools, compiled with a Postgres checkpointer, on thread `{analyst_id}:{incident_id}:reviewer` | Sections 5 and 8: its own checkpointer thread; section 9: it holds `search_knowledge_base` |
| The agent adds the task whenever a run starts, and the brief only when the history is empty | The Reviewer's thread is reused, so each iteration's dossier has to reach the model |
| Every loop has two caps: the round budget or `max_review_iterations`, plus `graph_recursion_limit` on each invoke; hitting the recursion limit means no proposal or verdict, not a crash | Section 5: every loop has a structured condition and an independent hard cap |
| The checkpointer is built in the graph layer (`nodes/review.py`), not in `repository.py` | Trainer template: the checkpointer is passed in at `compile()` |

## Not implemented

- The Coordinator: `supervisor_node`, `route_after_supervisor`, its typed plan, and why each worker was dispatched.
- The parent graph (`graph/state.py`, `graph/graph.py`): `analyst_id` and `tasks` in state, the reducers (`dossier` with `operator.or_`, `reviews` append, `tasks` merge), a separate edge from each worker into the Reviewer, and `ReviewVerdict` in the checkpoint serializer's allowed modules.
- The eligibility check and output guardrails.
- `find_similar_incidents` for Hazard Control (comes with the Gateway ticket).
- The run record: the full list of rules-engine invocations (the dossier keeps only the latest decision per rule), tool calls, and token totals.
- Registering the Reviewer's thread in the `sessions` table.
- Known edge case: if the Reviewer runs out of rounds mid-tool-call, its thread keeps an unanswered tool call, and a later run on that thread would fail on Bedrock.
