# Graph

## Specialist loop

```
{incident, tasks}                                     parent state (GF-50)
      |
RECORDABILITY / REPORTABILITY node                    nodes/recordability.py, nodes/reportability.py
      |  invoke {worker, task, incident}
      v
   agent  -- tool calls, rounds < MAX -->  tools      specialists.py
     ^                                       |        (ToolNode over tools/tools.py; the tools write
     +------- no proposal accepted yet ------+         decisions, retrieved and proposal into state)
      |
      |  proposal accepted, the model stopped asking, or the budget is spent
      v
state["proposal"], state["decisions"]                 specialists.py
      |
{recordability | reportability: typed proposal or None, rule_invocations}
```

## Files

| File | Contains |
|---|---|
| `graph/specialists.py` | `SpecialistState`, `MAX_SPECIALIST_TOOL_ROUNDS`, and `build_specialist`, which makes each worker its own graph: the model picks tools and `ToolNode` runs them. Plain-Python routers end the loop on a structured event (an accepted proposal in state), when the model stops asking, or when the budget is spent. `get_specialists` builds both once. |
| `graph/nodes/recordability.py` | The RECORDABILITY node: runs the Recordability Worker on the incident and returns only its `ClassificationProposal` and the rule invocations its tools made. |
| `graph/nodes/reportability.py` | The REPORTABILITY node: the same for the Reportability Worker and its `ReportingProposal`. |
| `tools/tools.py` | The `@tool` functions (`get_incident_extraction`, `search_knowledge_base`, `evaluate_rule`, `propose_classification`, `propose_reporting_determination`) and each worker's tool list. The propose tools take a typed proposal (section 9); the others take plain arguments. All read the incident from the injected state, never from the model. `evaluate_rule`, `search_knowledge_base` and the propose tools write what they found into the specialist's state with `Command`, so nothing is read back out of messages. |
| `rules/proposal_review.py` | `review_classification` and `review_reporting` take a typed proposal and return its problems, like `enforce_grounding` in the trainer's `rag.py`: it is accepted only if its fields match the rule decisions and every cited chunk was retrieved. Nothing is written. |
| `prompts.py` | Each worker's system prompt and default goal. |
| `rules/engine.py` | `evaluate_rule`, the plain-dict way into the rules for the tools. It owns the rule ordering (`NEEDS`: R1 uses R3, R4 uses R1) and raises `RuleError` when a rule's prerequisite hasn't run, which the tool hands back to the model as an error. Also the `r*_inputs` builders shared with `evaluate_incident`. |
| `rules/reporting.py` | R2 names the 1904.39(b)(10) or (b)(11) exclusion it applied, which is how a proposal that stops at the clock gets rejected. |

Paths are relative to `src/fieldsight/`. The pydantic models (`ClassificationProposal`, `ReportingProposal`, `Exclusion`) are in `schemas/rule_proposal.py`, and `RuleDecision.exclusion` is in `schemas/rule_decision.py`.

For GF-50: the parent state supplies `incident` (a plain dict) and an optional `tasks[name]` narrowed goal, and receives the proposal key plus `rule_invocations`, which needs a list-append reducer.
