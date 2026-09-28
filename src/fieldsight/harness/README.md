# Harness

## Chart

```
raw request + cracked strings + NormalizedIncident
      |
check_turn                                                              turn_check.py
   1. input validation       TURN_REQUEST: command, incident id, question length,
                             artifact type and size; submit needs artifacts, ask a question
   2. Prompt Attacks         aws/guardrails.screen on the question and every cracked string;
                             an attacked question is refused, an attacked artifact string is withheld
   3. readiness gate         label: analyze is classify; ask goes to the fast model (classify())
                             then the deterministic check regardless of the label:
                             a record, REQUIRED_FIELDS, R5 (recorded as an invocation)
      |
      +-- policy_question --> answer_from_retrieval
      +-- classify ---------> run_workflow, or route_to_analyst if the check found problems
      +-- action -----------> refused: nothing is written without the two-person review
      +-- out_of_scope -----> refused, naming the escalation path
      |
(the workflow runs: Coordinator, workers, Reviewer)
      |
   4. output guardrails
      guard_answer                                                      answer_guard.py
         uncited claim or unresolved citation --> regenerate with the objection
         threshold with no invocation this turn --> run the rules, inject the result, regenerate
         determination-shaped language --> regenerate once, then refuse (gate miss)
         PII --> redact, never regenerate;   no disclosure --> append it
      guard_dossier                                                     dossier_guard.py
         each leg's thresholds re-checked against this turn's invocations --> blocked legs to re-dispatch

every failure --> emit(): a structured log line with the correlation id, and an event in the result
```

## Files

| File | Contains |
|---|---|
| `turn_check.py` | `check_turn` (stages 1 to 3), `classify` (the fast-model label), `REQUIRED_FIELDS` and `ROUTES`. |
| `answer_guard.py` | `guard_answer` (stage 4 on a generated answer), `THRESHOLDS` and `MAX_REGENERATIONS`. |
| `dossier_guard.py` | `guard_dossier` (stage 4 on the dossier) and `LEG_REVIEWS`. |
| `common.py` | `emit`, `refuse`, `citation_problems`, `latest`, `DISCLOSURE` and the `DETERMINATION` patterns. |
| `escalation.py` | `evaluate_escalation` (the OR-ed review triggers), `EscalationPolicy` (near-boundary margins) and `EscalationSignals`. |
| `bounds.py` | `BoundsConfig`, `preflight` (check-and-stop before each leg), `record_usage` and `start_turn`. |
| `analysis.py` | `analyze_incident`: runs the rules and escalation on a stored incident and saves the run. |
| `review_decisions.py` | `decide_review`, the side-effect-free check of a human approve, edit then approve, or reject. |
| `review_flow.py` | `submit_review` and the `ReviewStore` protocol that records one decision on a pending queue item. |

Paths are relative to `src/fieldsight/harness/`. The shapes (`TurnRequest`, `GuardrailEvent`, `Refusal`) are in `types/guardrails.py`, and the classifier's `ReadinessClassification` is in `schemas/readiness.py`.

## Decisions

| Decision | Why |
|---|---|
| The stages are functions the caller runs in order, not graph nodes | Section 10: the harness wraps every turn, including `ask`, around the workflow |
| Input is validated with a TypeAdapter before any model call | Section 10 stage 1: a typed request model, length caps, artifact type and size checks |
| An attacked question refuses the turn; an attacked artifact string is withheld and the turn goes on | The question is the analyst's own intent; a poisoned artifact shouldn't stop the incident, and `prompt_attack_detected` routes it to review through `escalation.py` |
| `analyze` is labelled `classify` without a model call; only `ask` is classified by the fast model | The command already says what the analyst wants |
| The deterministic check runs whatever the label, and can only turn `run_workflow` into `route_to_analyst` | Section 10: it can stop a classify turn, never start one |
| R5 runs through the rules engine and is recorded as an invocation; the model's confidence is never an input | Sections 6 and 10 |
| An unattributed threshold is fixed by the harness running the rules (`evaluate_incident`), never the model's `evaluate_rule` tool | Section 6: the harness path is authoritative, and both paths record an invocation |
| In `guard_dossier`, this turn's harness invocations win over a leg's own tool-path decisions | Section 6: a threshold with no recorded invocation this turn is blocked |
| Each failure type has its own remedy | Section 10's remedies table |
| Every failure is an event with the correlation id, the remedy and the trigger, never the PII itself | Section 10: no failure is silently repaired |
| `citations_supported` and `prompt_attack_detected` are returned for `EscalationSignals` | Section 10: both are escalation triggers |

## Not implemented

- Nothing calls these yet: `submit`, `analyze` and `ask` (GF-57) and the Coordinator (GF-50) will.
- Events and rule invocations are logged and returned, not persisted; that's the run record (GF-53).
- Stage 4 checks that a citation resolves, not that the chunk supports the claim; the Reviewer judges support.
- The poisoned-packet fixture and the injection-resistance demo (GF-58).
