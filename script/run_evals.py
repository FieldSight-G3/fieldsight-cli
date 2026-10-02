"""Run the golden set (evals/golden/) and the escalation cases (evals/escalation/), and write the results the
evaluation report is built from.

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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fieldsight.evaluation.deterministic import run_case as run_ci_case
from fieldsight.evaluation.deterministic import run_pairs
from fieldsight.evaluation.golden import (
    ESCALATION,
    GOLDEN,
    load_all,
    load_cases,
    set_problems,
)

RESULTS = Path(__file__).resolve().parents[1] / "evals" / "results"
ALICE = "ae9e1561-5c6d-59bb-8662-75b0871dbfa2"  # the seeded analyst granted the demo establishments
# §14 refusal precision and recall: these must refuse, these must answer
MUST_REFUSE = {"out_of_corpus"}
MUST_ANSWER = {"near_miss", "single_document", "multi_hop", "threshold"}


def ci(cases: list[dict]) -> int:
    problems = set_problems(load_cases(GOLDEN), load_cases(ESCALATION)) + run_pairs(load_all())
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


def live(cases: list[dict], analyst: UUID, grounding: bool, workers: int, reuse_packets: bool = False) -> list[dict]:
    """ every case and variant, in groups run in parallel

        Setup runs first, one at a time: each packet is submitted once (or reused, with reuse_packets) and each case
        given its own copy of its packet's incident, so no two cases share threads, a session or a queue row and every
        case runs in parallel. A policy question on the shared context incident runs no workflow.
        A variant that replaces a module function (retrieval_disabled) runs alone at the end.
    """

    from fieldsight.evaluation.live import (
        CONTEXT_INCIDENT,
        Incidents,
        LiveResult,
        run_case,
    )
    from fieldsight.graph.nodes.review import get_reviewer
    from fieldsight.graph.specialists import get_specialists

    incidents = Incidents(analyst, RESULTS / ".packet-cache.json" if reuse_packets else None)
    get_specialists(), get_reviewer()  # built once here, so parallel cases never race to build them

    jobs: list[tuple[int, dict, dict | None, str | None, str | None]] = []
    for case in cases:
        try:
            for folder in incidents.packets(case):
                incidents.submit(folder)
            incident_id, setup_error = incidents.resolve(case), None
        except Exception as error:  # noqa: BLE001 - a packet that won't submit fails its case, never the whole run
            incident_id, setup_error = None, f"setup: {type(error).__name__}: {error}"
        for variant in case.get("variants") or [None]:
            jobs.append((len(jobs), case, variant, incident_id, setup_error))
    print(f"setup done: {len(incidents.submitted)} packet(s) submitted, {len(jobs)} run(s)", flush=True)

    def run(job) -> tuple[int, LiveResult]:
        index, case, variant, incident_id, setup_error = job
        name = variant and variant.get("name")
        label = f"{case['id']}{' / ' + name if name else ''}"
        if setup_error:
            result = LiveResult(case["id"], case.get("category", ""), name, error=setup_error)
        else:
            result = run_case(case, incidents, variant=variant, judge_grounding=grounding, incident_id=incident_id)
        print(f"{'passed' if result.passed else 'FAILED'}  {label}{': ' + result.error if result.error else ''}", flush=True)
        return index, result

    def run_group(group: list) -> list[tuple[int, LiveResult]]:
        return [run(job) for job in group]

    alone = [job for job in jobs if job[2] and job[2].get("name") == "retrieval_disabled"]
    groups: dict[str, list] = {}
    for job in jobs:
        if job in alone:
            continue
        shared = job[3] is None or job[3] == CONTEXT_INCIDENT
        groups.setdefault(f"solo-{job[0]}" if shared else job[3], []).append(job)

    finished: list[tuple[int, LiveResult]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for done in pool.map(run_group, groups.values()):
            finished += done
    for job in alone:
        with retrieval_disabled():
            finished.append(run(job))
    return [{**asdict(result), "passed": result.passed} for _, result in sorted(finished, key=lambda pair: pair[0])]


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
        "groundedness": {verdict: grounded.count(verdict)
                         for verdict in ("supported", "partially_supported", "not_supported", "unjudged")},
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
    parser.add_argument("--set", choices=["golden", "escalation", "all"], default="all",
                        help="the 15 golden cases, the escalation cases, or both (default)")
    parser.add_argument("--cases", nargs="*", help="case ids to run within the set (default: every one)")
    parser.add_argument("--label", default="run", help="names the results folder, e.g. first-cited-answer or final")
    parser.add_argument("--analyst-id", default=ALICE)
    parser.add_argument("--no-grounding", action="store_true", help="skip the groundedness judge (faster, cheaper)")
    parser.add_argument("--workers", type=int, default=4, help="cases run at once (default 4; 1 runs in order)")
    parser.add_argument("--rerun-failed", action="store_true", help="run only the cases that failed in the latest results")
    parser.add_argument("--reuse-packets", action="store_true",
                        help="reuse packets submitted by an earlier run when their files haven't changed (not after "
                             "changing normalize or photo code)")
    parser.add_argument("--allow-remote", action="store_true", help="allow a non-local database (it writes run records)")
    parser.add_argument("--gateway", action="store_true",
                        help="read through the AgentCore Gateway (its API reads RDS, so only with --allow-remote on RDS)")
    args = parser.parse_args()

    cases = {"golden": load_cases(GOLDEN), "escalation": load_cases(ESCALATION), "all": load_all()}[args.set]
    if args.cases:
        unknown = set(args.cases) - {case["id"] for case in cases}
        if unknown:
            parser.error(f"no such case: {', '.join(sorted(unknown))}")
        cases = [case for case in cases if case["id"] in args.cases]
    if args.rerun_failed:
        latest = max(RESULTS.glob("*/results.json"), default=None, key=lambda path: path.parent.name)
        if latest is None:
            parser.error("no earlier results to rerun the failures of")
        failed = {case["case_id"] for case in json.loads(latest.read_text(encoding="utf-8"))["cases"] if not case["passed"]}
        cases = [case for case in cases if case["id"] in failed]
        print(f"rerunning {len(cases)} failed case(s) from {latest.parent.name}")

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
    RESULTS.mkdir(parents=True, exist_ok=True)
    results = live(cases, UUID(args.analyst_id), not args.no_grounding, max(1, args.workers), args.reuse_packets)
    numbers = metrics(results)
    folder = RESULTS / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.label}"
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps({"metrics": numbers, "cases": results}, indent=2, default=str),
                                         encoding="utf-8")
    (folder / "summary.md").write_text(summary(results, numbers, args.label), encoding="utf-8")
    print(f"\n{numbers['passed']} of {numbers['cases']} passed; results in {folder}")


if __name__ == "__main__":
    main()
