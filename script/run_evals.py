"""Run the golden set (evals/golden/) and write the results the evaluation report is built from.

    python script/run_evals.py --tier ci                     # deterministic: no model, no AWS; exits 1 on a failure
    python script/run_evals.py --tier live                   # every case through the harness, with the judge
    python script/run_evals.py --tier live --cases single-01 ooc-01 --label first-cited-answer

The live tier submits the golden packets and writes run records to the database FIELDSIGHT_DATABASE_URL points at,
so it refuses a remote database unless --allow-remote is given. Results go to evals/results/<UTC time>-<label>/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fieldsight.evaluation.deterministic import run_case as run_ci_case
from fieldsight.evaluation.deterministic import run_pairs
from fieldsight.evaluation.golden import load_cases, set_problems

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results"
ALICE = "ae9e1561-5c6d-59bb-8662-75b0871dbfa2"  # the seeded analyst granted the demo establishments
# §14 refusal precision and recall: these must refuse, these must answer
MUST_REFUSE = {"out_of_corpus"}
MUST_ANSWER = {"near_miss", "single_document", "multi_hop", "threshold"}


def ci(cases: list[dict]) -> int:
    problems = set_problems(cases) + run_pairs(cases)
    results = [run_ci_case(case) for case in cases]
    for result in results:
        detail = "; ".join(result.problems) or "; ".join(result.checks) or result.reason
        print(f"{result.status:8} {result.case_id:18} {detail}")
    for problem in problems:
        print(f"set      {problem}")
    failed = [r for r in results if r.status == "failed"]
    print(f"\n{sum(r.status == 'passed' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r.status == 'skipped' for r in results)} live-only, {len(problems)} set problem(s)")
    return 1 if failed or problems else 0


@contextmanager
def retrieval_disabled():
    """ adversarial-01's second variant: every Knowledge Base search fails, as if retrieval were down """

    from fieldsight.errors import RetrievalError
    from fieldsight.retrieval import evidence

    original = evidence.search

    def down(*args: Any, **kwargs: Any) -> Any:
        raise RetrievalError("retrieval disabled for this evaluation variant")

    evidence.search = down
    try:
        yield
    finally:
        evidence.search = original


def live(cases: list[dict], analyst: UUID, grounding: bool) -> list[dict]:
    from fieldsight.evaluation.live import Incidents, run_case

    incidents = Incidents(analyst)
    results = []
    for case in cases:
        for variant in case.get("variants") or [None]:
            name = variant and variant.get("name")
            print(f"running {case['id']}{' / ' + name if name else ''} ...", flush=True)
            if name == "retrieval_disabled":
                with retrieval_disabled():
                    result = run_case(case, incidents, variant=variant, judge_grounding=grounding)
            else:
                result = run_case(case, incidents, variant=variant, judge_grounding=grounding)
            print(f"  {'passed' if result.passed else 'FAILED'}"
                  f"{': ' + result.error if result.error else ''}", flush=True)
            results.append({**asdict(result), "passed": result.passed})
    return results


def metrics(results: list[dict]) -> dict:
    """ refusal precision and recall, groundedness and statement rates, cost and latency """

    def refused(result: dict) -> bool | None:
        answers = [turn["refused"] for turn in result["turns"] if turn["refused"] is not None]
        return answers[-1] if answers else None

    scored = [(r["category"], refused(r)) for r in results if r["variant"] in (None, "retrieval_enabled")]
    should = [did for category, did in scored if category in MUST_REFUSE and did is not None]
    shouldnt = [did for category, did in scored if category in MUST_ANSWER and did is not None]
    true_refusals, false_refusals = sum(should), sum(shouldnt)
    grounded = [g["verdict"] for r in results for t in r["turns"] for g in t["grounded"]]
    judged = [j["present"] for r in results for t in r["turns"] for j in t["judged"]]
    turns = [t for r in results for t in r["turns"]]
    return {
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "refusal_precision": true_refusals / (true_refusals + false_refusals) if true_refusals + false_refusals else None,
        "refusal_recall": true_refusals / len(should) if should else None,
        "groundedness": {verdict: grounded.count(verdict) for verdict in ("supported", "partially_supported", "not_supported")},
        "statements_present": {present: judged.count(present) for present in ("yes", "partly", "no")},
        "cost_usd": round(sum(t["cost_usd"] for t in turns), 4),
        "seconds": {"total": round(sum(t["seconds"] for t in turns), 1),
                    "max_turn": max((t["seconds"] for t in turns), default=0)},
    }


def summary(results: list[dict], numbers: dict, label: str) -> str:
    lines = [f"# Golden set: {label}", "", f"{numbers['passed']} of {numbers['cases']} cases passed.", "",
             "| Metric | Value |", "|---|---|"]
    lines += [f"| {key} | {value} |" for key, value in numbers.items() if key not in ("cases", "passed")]
    lines += ["", "| Case | Category | Routes | Result | Failed checks | Unchecked |", "|---|---|---|---|---|---|"]
    for r in results:
        name = r["case_id"] + (f" / {r['variant']}" if r["variant"] else "")
        failed = "; ".join(f for t in r["turns"] for f in t["failed"]) or r["error"] or \
            "; ".join(t["error"] for t in r["turns"] if t["error"])
        unchecked = ", ".join(sorted({u for t in r["turns"] for u in t["unchecked"]}))
        routes = ", ".join(t["route"] or t["command"] for t in r["turns"])
        lines.append(f"| {name} | {r['category']} | {routes} | {'pass' if r['passed'] else 'FAIL'} | {failed} | {unchecked} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=["ci", "live"], required=True)
    parser.add_argument("--cases", nargs="*", help="case ids to run (default: all)")
    parser.add_argument("--label", default="run", help="names the results folder, e.g. first-cited-answer or final")
    parser.add_argument("--analyst-id", default=ALICE)
    parser.add_argument("--no-grounding", action="store_true", help="skip the groundedness judge (faster, cheaper)")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local database (it writes run records)")
    parser.add_argument("--gateway", action="store_true",
                        help="read through the AgentCore Gateway (its API reads RDS, so only with --allow-remote on RDS)")
    args = parser.parse_args()

    cases = load_cases()
    if args.cases:
        unknown = set(args.cases) - {case["id"] for case in cases}
        if unknown:
            parser.error(f"no such case: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in args.cases]

    if args.tier == "ci":
        sys.exit(ci(cases))

    from fieldsight.config import settings

    host = settings.database_url.rsplit("@", 1)[-1].split("/")[0]
    if not host.startswith(("localhost", "127.0.0.1")) and not args.allow_remote:
        parser.error(f"the live tier writes to the database at {host}; pass --allow-remote to run against it")

    if not args.gateway:
        # the Gateway's API reads RDS, never this database: without --gateway the workers read the harness's copy
        os.environ.pop("FIELDSIGHT_GATEWAY_URL", None)
        os.environ.pop("AGENTCORE_GATEWAY_FIELDSIGHTTOOLS_URL", None)

    # idempotent: the seeded analysts, grants, precedents and context incident every case relies on
    from fieldsight.seed import seed_demo

    print(f"seed: {seed_demo().model_dump()}")
    results = live(cases, UUID(args.analyst_id), not args.no_grounding)
    numbers = metrics(results)
    folder = RESULTS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.label}"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps({"metrics": numbers, "cases": results}, indent=2, default=str),
                                         encoding="utf-8")
    (folder / "summary.md").write_text(summary(results, numbers, args.label), encoding="utf-8")
    print(f"\n{numbers['passed']} of {numbers['cases']} passed; results in {folder}")


if __name__ == "__main__":
    main()
