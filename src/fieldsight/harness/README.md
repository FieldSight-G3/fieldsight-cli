# Harness

## Chart

```
run_turn(raw request, workflow, answerer)                               run/lifecycle.py
   load_record: the stored row, read once; normalized, photo_contradicts run/incident.py
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
      +-- classify ---------> run_workflow: the graph, under the meter  run/workflow.py, metering/
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
      model calls: the graph's from its transcripts, otherwise the turn meter's

later, a human: submit_review on a queued item                          escalation/review.py
   an approval closes the incident in the same transaction, under its idempotency key
every failure --> emit(): a structured log line with the correlation id, and an event in the result
```

## Files

Grouped by section 10's parts: guardrails, escalation, bounds, and the run that ties them together.

| File | Contains |
|---|---|
| `run/lifecycle.py` | `run_turn`: one turn start to finish, the entry point every command calls. |
| `run/wiring.py` | `turn`: one command as the verified analyst, with the grant check (a malformed incident id is denied too), metering from the session's saved spend, the Coordinator's graph (`graph/graph.graph_workflow`, wrapped by `harness_workflow` so a meter refusal still ends and records the turn, and the cited scores reach escalation) and the RAG answerer (`rag_answerer`) composed around `run_turn`. Also `submit` (a packet in, a new incident out) and `latest_run` (the run record `trace` reads). The CLI and the AgentCore Runtime both call it. |
| `run/incident.py` | `load_record`: the stored row, read once per turn, or None for an unknown id so `check_turn` routes to the analyst; `normalized` (its `NormalizedIncident`) and `photo_contradicts` (the escalation signal from the photo verdicts `submit` stored, None when no photo was judged). |
| `run/workflow.py` | The `Workflow` type: the Coordinator's graph as `run_turn` calls it. The turn meter (`metering/`) is the only budget. |
| `run/answer.py` | `answer_question` and the `Answerer` type: a policy question answered from retrieval through `guard_answer`. |
| `run/record.py` | `save_run`: the run record, the incident's outcome on `analyze`, and the review queue row; `metered_calls`, the turn meter's calls in the run record's model-call shape. |
| `guardrails/turn_check.py` | `validate_request` (stage 1), `screen_texts` (stage 2), `screen_review` (a reviewer's free text through the guardrail), `check_turn` (stages 1 to 3, for turns), `classify` (the fast-model label), `REQUIRED_FIELDS` and `ROUTES`. `submit` calls the first two directly, each once. |
| `guardrails/answer_guard.py` | `guard_answer` (stage 4 on a generated answer), `THRESHOLDS` and `MAX_REGENERATIONS`. |
| `guardrails/dossier_guard.py` | `guard_dossier` (stage 4 on the dossier, run by the graph's eligibility_check) and `LEG_REVIEWS`. |
| `guardrails/common.py` | `emit`, `refuse`, `citation_problems`, `latest`, `DISCLOSURE` and the `DETERMINATION` patterns. |
| `escalation/triggers.py` | `evaluate_escalation` (the OR-ed review triggers) and the near-boundary observations it records. |
| `escalation/snapshot.py` | `ReviewSnapshot`: the dossier as submitted, frozen onto the queue row when a turn escalates, with each cited chunk mapped to its document as a `CitationReference`. |
| `escalation/pending.py` | `PendingReview`: a queued review as the reviewer reads it back, with the queue row's trusted metadata and its frozen snapshot. |
| `escalation/review.py` | `decide_review` (the side-effect-free check of a human approve, edit then approve, or reject), and `submit_review` with the `ReviewStore` protocol that records one decision on a pending queue item and, for an approval, the write after approval under its execution key. |
| `bounds.py` | `BoundsConfig`, `preflight` (check-and-stop before each leg), `record_usage` and `start_turn`. |
| `bounds_runtime.py` | `TurnBudget`: one turn's thread-safe budget shared by concurrent legs, reserving tool batches all-or-nothing, and `BoundStopped`. |
| `idempotency.py` | `idempotency_key` (a `uuid5` of session, tool and arguments; each tool call's `args_hash` in the run record) and `canonicalize` (mapping keys and sets order-independent, equal numbers normalized, NaN and non-string keys refused). |

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
| Each tool call's `args_hash` in the run record is its idempotency key, with the agent's checkpointer thread as the session | Section 9: the same call in the same session always records the same key |
| An approval closes the incident (`status = 'closed'`) in the transaction that records the decision, keyed by `idempotency_key(queue id, "execution", decision)`; a retry with the same key applies once, another key is a conflict | Section 9's harness-only write after approval, and section 13: "retry with the same key" |
| The session's spend is kept on the analyst's Coordinator session row; `turn` starts the meter from it and adds the turn's spend after, even when the turn fails | Section 10: the cost ceiling is per session and accumulates across turns |
| Model calls outside the graph (readiness, the answer, and on `submit` the normalizer and photo checks) are recorded from the turn meter, labelled with the command | The meter already prices every prompted call; only the graph's transcripts name each agent |
| The Workflow and Answerer are passed in as callables | `wiring.turn` composes the real graph and retrieval chain; tests stub both |

## Not implemented

- Guardrail events are returned in `TurnRun` and logged, not persisted: `run_records` has no column for them (GF-53).
- Every escalated turn adds a review queue row, so re-running `analyze` on a queued incident queues it again; once one is approved, approving another is refused.
- An `ask` the readiness model labels `classify` runs the graph, so the run record keeps the graph's calls and not that readiness call.
- An edit then approve keeps the edited narrative only in the queue row's decision; nothing copies it onto the incident.
- Stage 4 checks that a citation resolves, not that the chunk supports the claim; the Reviewer judges support.
- The poisoned-packet fixture and the injection-resistance demo (GF-58).
