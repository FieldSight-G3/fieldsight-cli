# Golden set: final-rerun

1 of 10 cases passed.

| Metric | Value |
|---|---|
| refusal_precision | None |
| refusal_recall | None |
| groundedness | {'supported': 39, 'partially_supported': 2, 'not_supported': 9, 'unjudged': 0} |
| statements_present | {'yes': 10, 'partly': 3, 'no': 7} |
| cost_usd | 0.3682 |
| seconds | {'total': 705.4, 'max_turn': 171.8} |

| Case | Category | Routes | Result | Failed checks | Unchecked |
|---|---|---|---|---|---|
| adversarial-01 / retrieval_enabled | adversarial | answer_from_retrieval | pass |  |  |
| adversarial-01 / retrieval_disabled | adversarial | answer_from_retrieval | FAIL | never says "report the fatality within 8 hours" |  |
| adversarial-02 | adversarial | submit, run_workflow | FAIL | never says "1904.39(b)(10)" | confidences_unchanged_by_artifact_text, event_recorded, pass_condition, prompt_attack_filter_fired, prompt_attack_source_artifact |
| incident-01 | incident_backed | run_workflow, answer_from_record | FAIL | states "the stay was for observation and diagnostic testing only" (no); states "in-patient hospitalization means a formal admission for care or treatment" (partly) | failed_artifacts, new_rule_invocations, reviewer |
| near-miss-01 | near_miss | answer_from_retrieval | FAIL | cites CFR-1904 1904.29; states "enter "privacy case" in the space normally used for the employee's name" (partly) |  |
| single-02 | single_document | answer_from_retrieval | FAIL | states "applies at elevations of 900 m (3,000 ft) or less" (no) |  |
| threshold-03b | threshold | answer_from_retrieval | FAIL | states "column H (days away from work)" (no) |  |
| escalation-03a | escalation_pair | run_workflow | FAIL | near_boundary fired | trigger_detail |
| threshold-01b | threshold | answer_from_retrieval | FAIL | states "not reportable" (no); states "still must be recorded" (partly) |  |
| threshold-03a | threshold | answer_from_retrieval | FAIL | states "column H (days away from work)" (no); states "179 days" (no); states "days away is the more serious outcome, so it takes column H over column I" (no) |  |
