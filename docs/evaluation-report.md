# Evaluation report (§16.3)

## Golden set
Table of all cases: id, category, expected, result.

## Per-category results

## Similarity threshold
Value, and the method: run the golden set, plot scores of correct vs incorrect answers,
choose where they separate.

## Judged runs
First run (date) vs final run (date); delta and analysis.

## Adversarial cases
All four, with transcripts / run-record excerpts.

## Refusal precision / recall

## Cost and latency (measured from run records)
| Operation | Target | Measured |
|---|---|---|
| Retrieval | < 800 ms | |
| Rules-engine evaluation | < 10 ms | |
| Routing decision | < 2 s | |
| Grounded policy answer | < 10 s | |
| Full dossier from normalized record | < 30 s | |

Cost per incident per scenario; cost per extra reflection iteration; fast vs reasoning tier.
