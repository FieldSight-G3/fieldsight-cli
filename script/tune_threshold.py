""" tune the retrieval threshold: the score that best separates answerable from out-of-corpus golden cases

    run from the repo root once evals/golden/ is populated:  python script/tune_threshold.py
    then set FIELDSIGHT_RETRIEVAL_SCORE_THRESHOLD to the printed value and record it in docs/evaluation-report.md
"""

import json
from itertools import pairwise
from pathlib import Path

from fieldsight.retrieval.corpus import search
from fieldsight.retrieval.references import pick_filter

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "golden"

# categories the score alone must refuse or answer; the rest (determination probes, adversarial,
# multi-turn) are handled by the harness, so they don't tune it
REFUSE = {"out_of_corpus"}
ANSWER = {"single_document", "multi_hop", "threshold", "incident_backed", "near_miss"}


def golden_cases() -> list[dict]:
    """ single-query golden cases the score decides """

    cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(GOLDEN.glob("*.json"))]
    return [case for case in cases if "query" in case and case["category"] in REFUSE | ANSWER]


def top_score(query: str) -> float:
    """ best ungated score from the pipeline's first search """

    doc_type, section_path, _ = pick_filter(query)
    hits = search(query, doc_type=doc_type, section_path=section_path, gated=False)
    if not hits and (doc_type or section_path):
        hits = search(query, gated=False)
    return max((hit.metadata["score"] for hit in hits), default=0.0)


def errors(threshold: float, answer: list[float], refuse: list[float]) -> int:
    """ answerable cases refused plus out-of-corpus cases answered """

    return sum(score < threshold for score in answer) + sum(score >= threshold for score in refuse)


def separate(answer: list[float], refuse: list[float]) -> float:
    """ fewest-error threshold, midway between adjacent scores, preferring the widest gap """

    scores = sorted(set(answer + refuse))
    candidates = [(low + high) / 2 for low, high in pairwise(scores)] or scores
    return min(candidates, key=lambda t: (errors(t, answer, refuse), -min(abs(t - s) for s in scores)))


if __name__ == "__main__":
    cases = golden_cases()
    if not cases:
        raise SystemExit(f"no golden cases in {GOLDEN}; the golden set has to be written before the threshold can be tuned")

    scored = [(case, top_score(case["query"])) for case in cases]
    answer = [score for case, score in scored if case["category"] in ANSWER]
    refuse = [score for case, score in scored if case["category"] in REFUSE]
    if not (answer and refuse):
        raise SystemExit("tuning needs at least one answerable and one out-of-corpus case")

    threshold = separate(answer, refuse)
    print(f"{'id':<24} {'category':<18} {'expect':<8} {'top score':>9}  result")
    for case, score in sorted(scored, key=lambda pair: pair[1]):
        expect = "refuse" if case["category"] in REFUSE else "answer"
        got = "answer" if score >= threshold else "refuse"
        print(f"{case['id']:<24} {case['category']:<18} {expect:<8} {score:>9.3f}  {'ok' if got == expect else 'WRONG'}")

    print(f"\nanswerable top scores: {min(answer):.3f} to {max(answer):.3f}")
    print(f"out-of-corpus top scores: {min(refuse):.3f} to {max(refuse):.3f}")
    print(f"threshold {threshold:.3f}, {errors(threshold, answer, refuse)} of {len(scored)} cases on the wrong side")
