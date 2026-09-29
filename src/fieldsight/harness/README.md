# Harness

## Chart

```
run_turn(raw request, workflow, answerer)                               run/lifecycle.py
   load_incident: the stored record, or None                            run/incident.py
      |
   check_turn                                                           guardrails/turn_check.py
      1. input validation    TURN_REQUEST: command, incident id, question length,
                             artifact type and size; submit needs artifacts, ask a question
      2. Prompt Attacks      aws/guardrails.screen on the question and every cracked string;
                             an attacked question is refused, an attacked artifact string is withheld
      3. readiness gate      label: analyze is classify; ask goes to the fast model (classify())
                             then the deterministic check regardless of the label:
                             a record, REQUIRED_FIELDS, R5 (recorded as an invocation)
      |
      +-- policy_question --> answer_question                           run/answer.py
      |                          4. guard_answer                        guardrails/answer_guard.py
      |                             uncited claim or unresolved citation --> regenerate with the objection
      |                             threshold with no invocation --> run the rules, inject, regenerate
      |                             determination-shaped language --> regenerate once, then refuse
      |                             PII --> redact, never regenerate;  no disclosure --> append it
      +-- classify ---------> run_workflow: preflight, then the graph   run/workflow.py, bounds.py
      |                          Coordinator, workers, Reviewer, then eligibility_check:
      |                          4. guard_dossier                       guardrails/dossier_guard.py
      |                             blocked legs --> back to the Coordinator; still blocked at the cap --> withheld
      |                       or route_to_analyst if the readiness check found problems
      +-- action -----------> refused: nothing is written without the two-person review
      +-- out_of_scope -----> refused, naming the escalation path
      |
   evaluate_escalation: the harness's own rule run and the signals     escalation/triggers.py
      the dossier stands, or goes to the review queue
      |
   save_run: the run record, the outcome on analyze, the queue row      run/record.py

later, a human: submit_review on a queued item                          escalation/review.py
every failure --> emit(): a structured log line with the correlation id, and an event in the result
```

## Files

Grouped by section 10's parts: guardrails, escalation, bounds, and the run that ties them together.

| File | Contains |
|---|---|
| `run/lifecycle.py` | `run_turn`: one turn start to finish, the entry point every command calls. |
| `run/incident.py` | `load_incident`: the stored record, or None for an unknown id so `check_turn` routes to the analyst. |
| `run/workflow.py` | `run_workflow` and the `Workflow` type: the bounds check, then the Coordinator's graph. |
| `run/answer.py` | `answer_question` and the `Answerer` type: a policy question answered from retrieval through `guard_answer`. |
| `run/record.py` | `save_run`: the run record, the incident's outcome on `analyze`, and the review queue row. |
| `guardrails/turn_check.py` | `check_turn` (stages 1 to 3), `classify` (the fast-model label), `REQUIRED_FIELDS` and `ROUTES`. |
| `guardrails/answer_guard.py` | `guard_answer` (stage 4 on a generated answer), `THRESHOLDS` and `MAX_REGENERATIONS`. |
| `guardrails/dossier_guard.py` | `guard_dossier` (stage 4 on the dossier, run by the graph's eligibility_check) and `LEG_REVIEWS`. |
| `guardrails/common.py` | `emit`, `refuse`, `citation_problems`, `latest`, `DISCLOSURE` and the `DETERMINATION` patterns. |
| `escalation/triggers.py` | `evaluate_escalation` (the OR-ed review triggers) and the near-boundary observations it records. |
| `escalation/review.py` | `decide_review` (the side-effect-free check of a human approve, edit then approve, or reject), and `submit_review` with the `ReviewStore` protocol that records one decision on a pending queue item. |
| `bounds.py` | `BoundsConfig`, `preflight` (check-and-stop before each leg), `record_usage` and `start_turn`. |
| `bounds_runtime.py` | `TurnBudget`: one turn's thread-safe budget shared by concurrent legs, reserving tool batches all-or-nothing, and `BoundStopped`. |
| `idempotency.py` | `idempotency_key` (a `uuid5` of session, tool and arguments) and `canonicalize` (mapping keys and sets order-independent, equal numbers normalized, NaN and non-string keys refused). |
| `analysis.py` | `analyze_incident` and `ReviewSnapshot`: the rules and escalation on a stored incident, queued with its snapshot; called by the graph's eligibility node. Overlaps `run/`; see Not implemented. |

Paths are relative to `src/fieldsight/harness/`. The shapes (`TurnRequest`, `GuardrailEvent`, `Refusal`) are in `types/guardrails.py`, the escalation shapes (`EscalationPolicy`, `EscalationSignals`, `EscalationDecision`) in `types/escalation.py`, `WorkflowResult` and `TurnRun` in `types/run.py`, and the classifier's `ReadinessClassification` is in `schemas/readiness.py`.

## Decisions

| Decision | Why |
|---|---|
| The stages are functions the caller runs in order, not graph nodes | Section 10: the harness wraps every turn, including `ask`, around the workflow |
| Input is validated with a TypeAdapter before any model call | Section 10 stage 1: a typed request model, length caps, artifact type and size checks |
| An attacked question refuses the turn; an attacked artifact string is withheld and the turn goes on | The question is the analyst's own intent; a poisoned artifact shouldn't stop the incident, and `prompt_attack_detected` routes it to review through `escalation/triggers.py` |
| `analyze` is labelled `classify` without a model call; only `ask` is classified by the fast model | The command already says what the analyst wants |
| The deterministic check runs whatever the label, and can only turn `run_workflow` into `route_to_analyst` | Section 10: it can stop a classify turn, never start one |
| R5 runs through the rules engine and is recorded as an invocation; the model's confidence is never an input | Sections 6 and 10 |
| An unattributed threshold is fixed by the harness running the rules (`evaluate_incident`), never the model's `evaluate_rule` tool | Section 6: the harness path is authoritative, and both paths record an invocation |
| In `guard_dossier`, this turn's harness invocations win over a leg's own tool-path decisions | Section 6: a threshold with no recorded invocation this turn is blocked |
| Each failure type has its own remedy | Section 10's remedies table |
| Every failure is an event with the correlation id, the remedy and the trigger, never the PII itself | Section 10: no failure is silently repaired |
| `citations_supported` and `prompt_attack_detected` are returned for `EscalationSignals` | Section 10: both are escalation triggers |
| Every turn goes through `run_turn` and leaves a run record, refused or not | Section 10: every turn, including `ask`, gets the same guardrails, bounds, output checks and run record |
| `guard_dossier` runs inside the graph (its `eligibility_check`), not in `run_turn`; `run_turn` reads what it found from `WorkflowResult` | Section 5: the Coordinator re-dispatches on rejected citations, and section 10's remedy is to regenerate, which for a dossier is a re-dispatch |
| A leg still blocked when the graph's caps run out is withheld from `TurnRun.dossier` and kept in `blocked` | Section 10: output guardrails block the claim, and when regeneration is spent the remedy is to refuse, as `guard_answer` does |
| Escalation uses the harness's own `evaluate_incident`, run after the workflow | Section 10: the harness evaluates deterministic signals and lets the dossier stand or queues it |
| A signal no stage produced stays None, so escalation records it as unevaluated | Section 10: a model's confidence is never an input, and auto-release needs every check evaluated |
| Only `analyze` writes `incidents.outcome` | An `ask`, even one re-running a rule on a hypothetical, must not overwrite the determination |
| Idempotency keys are `uuid5` of `(session_id, tool_name, canonical arguments)`, computed by the harness | Section 9: keys come from the harness, and canonicalization is order-independent and tested; `uuid5` is deterministic, so a retry gets the same key |
| Canonical arguments sort mapping keys and set members, but keep list order | A list's order carries meaning (citations, chunk ids); a mapping's and a set's don't |
| The Workflow and Answerer are passed in as callables | The Coordinator's graph doesn't exist yet, so tests stub both |

## Not implemented

- Two save paths: the graph's eligibility node calls `analyze_incident`, which writes a run record and queue row inside the graph, and `run_turn` writes its own after the graph. Wiring the node into `run_turn` must pick one, or every analyze leaves two run records.
- Nothing calls `run_turn` yet: the CLI commands (GF-57) will. The real `Workflow` needs the Coordinator and the parent graph (GF-50).
- Guardrail events are returned in `TurnRun` and logged, not persisted: `run_records` has no column for them (GF-53).
- `SessionUsage` is returned in `TurnRun`, not persisted, so the session cost ceiling resets between commands until it has a table.
- Nothing uses `idempotency_key` yet: the tool dispatcher needs to compute it from each tool call's `args` and the session's thread id, and skip or replay a call whose key it has already seen.
- Every escalated turn adds a review queue row, so re-running `analyze` on a queued incident queues it again.
- Stage 4 checks that a citation resolves, not that the chunk supports the claim; the Reviewer judges support.
- The poisoned-packet fixture and the injection-resistance demo (GF-58).
