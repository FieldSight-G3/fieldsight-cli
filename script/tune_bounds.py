""" tune the graph's bounds and retrieval config from measured turns

    run from the repo root against the live database and Knowledge Base:
        python script/tune_bounds.py                        measure the analyze and ask turns already recorded
        python script/tune_bounds.py packets                list the packets under packets/
        python script/tune_bounds.py packets inc-0412 ...   submit each packet and analyze it through the real graph
        python script/tune_bounds.py packets all            and KB, then measure only those turns (real Bedrock spend)
    then set the printed values in .env, the ECS task definition and the AgentCore Runtime's environment, and record
    each with its measured basis in the architecture document's decisions table
"""

import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv

# the caps in force before this script raises any, read the way settings reads them
load_dotenv()
from fieldsight.harness.bounds import BoundsConfig

CURRENT = BoundsConfig.from_environment()
CURRENT_MAX_CHUNKS = int(os.environ["FIELDSIGHT_RETRIEVAL_MAX_CHUNKS"])

PACKETS = Path("packets")
FOLDERS = sorted(path for path in PACKETS.iterdir() if path.is_dir())
ARGS = sys.argv[1:]
if ARGS[:1] == ["packets"] and len(ARGS) == 1:
    for folder in FOLDERS:
        print(f"{folder.name}: {', '.join(sorted(path.name for path in folder.iterdir() if path.is_file()))}")
    raise SystemExit("\nrun one or more with: python script/tune_bounds.py packets <name> ... (or packets all)")
CHOSEN = (FOLDERS if ARGS[1:] == ["all"] else [PACKETS / name for name in ARGS[1:]]) if ARGS[:1] == ["packets"] else []
if missing := [folder.name for folder in CHOSEN if not folder.is_dir()]:
    raise SystemExit(f"no packet {', '.join(missing)}; the packets are {', '.join(folder.name for folder in FOLDERS)}")

# what the tuning turns run under. The round cap and the Reviewer iterations stay as they are, since raising them
# makes every turn longer; the caps that cost no time are raised so they can't cut a turn off. The graph reads them
# from settings when fieldsight is imported, so they're set first.
EXPLORE = {"FIELDSIGHT_BOUNDS_MAX_GRAPH_RECURSION_DEPTH": "80", "FIELDSIGHT_BOUNDS_MAX_TURN_WALL_CLOCK_SECONDS": "1800",
           "FIELDSIGHT_BOUNDS_SESSION_COST_CEILING_USD": "50", "FIELDSIGHT_RETRIEVAL_MAX_CHUNKS": "20"}
if CHOSEN:
    os.environ.update(EXPLORE)

from sqlalchemy import select

from fieldsight.config import settings
from fieldsight.harness.metering.meter import CHARS_PER_TOKEN
from fieldsight.repository import RunRepository
from fieldsight.schemas.agents import AgentName

# a bound is a hard cap, so the largest measured value has to clear it with room to spare
HEADROOM = 1.5
# output token allowances round up to a multiple of this
TOKEN_STEP = 256
# with fewer graph turns than this, the recommendation is a guess
MIN_TURNS = 5
# P4 needs one Reviewer rejection and a narrowed re-dispatch (section 5), so the cycle needs two iterations
MIN_REVIEWER_ITERATIONS = 2
AGENTS = get_args(AgentName)
# the tools whose results are corpus chunks in the worker's context
RETRIEVAL_TOOLS = ("search_knowledge_base", "read_provision")


def items(column: dict | None) -> list:
    return (column or {}).get("items") or []


def chunks_returned(invocation: dict) -> list[list[dict]]:
    """ the chunk lists one retrieval tool call returned, best first: one per search, one per provision read """

    try:
        outcome = json.loads(invocation["outcome"] or "{}")
    except json.JSONDecodeError:
        return []    # an error the tool returned, not results
    if invocation["tool"] == "search_knowledge_base":
        return [outcome.get("results") or []]
    return [hits for hits in (outcome.get("provisions") or {}).values() if isinstance(hits, list)]


def measure(runs: list[dict], seconds: dict[str, float]) -> dict:
    """ the largest value each bound has had to allow, across the turns the graph ran; seconds is each driven turn's
        measured wall clock by run id, since the run record keeps no end-to-end duration """

    tokens: dict[str, int] = defaultdict(int)          # agent -> most output tokens in one call
    rounds, tool_calls, iterations, steps, chunks, chunk_tokens, depth = [], [], [], [], [], [], [0]
    spend: dict[str, Decimal] = defaultdict(Decimal)    # incident -> dollars across its analyze and ask turns
    for run in runs:
        calls = items(run["model_calls"])
        for call in calls:
            spend[str(run["incident_id"])] += Decimal(str(call["cost_usd"]))
        plans = (run["workers_dispatched"] or {}).get("plans")
        if not plans:
            continue    # the graph didn't run this turn
        for call in calls:
            if call["agent"] in AGENTS:
                tokens[call["agent"]] = max(tokens[call["agent"]], call["output_tokens"])
        # one model call is one round; a worker re-dispatched after a rejection runs a leg per dispatch
        per_agent = Counter(call["agent"] for call in calls)
        dispatched = Counter(dispatch["worker"] for plan in plans for dispatch in plan["dispatches"])
        rounds += [math.ceil(per_agent[worker] / count) for worker, count in dispatched.items()]
        verdicts = len(items(run["reviewer_verdicts"]))
        if verdicts:
            rounds.append(math.ceil(per_agent["reviewer"] / verdicts))
        iterations.append(verdicts)
        invocations = items(run["tool_invocations"])
        tool_calls.append(len(invocations))
        # the parent graph's supersteps: per plan the Coordinator, the workers (one superstep, run in parallel) and
        # the Reviewer, or the Coordinator alone when it dispatched no one; then the eligibility check
        steps.append(sum(3 if plan["dispatches"] else 1 for plan in plans) + 1)

        # retrieval: every chunk the turn's tools put in front of a worker, and how deep in a search's results the
        # chunks the dossier cites sat, which is how many results a search has to return
        cited = {chunk for leg in (run.get("dossier") or {}).values() for chunk in (leg.get("cited") or {})}
        returned = [hits for call in invocations if call["tool"] in RETRIEVAL_TOOLS for hits in chunks_returned(call)]
        chunks.append(sum(len(hits) for hits in returned))
        chunk_tokens.append(sum(len(hit.get("text", "")) for hits in returned for hit in hits) // CHARS_PER_TOKEN)
        searches = [hits for call in invocations if call["tool"] == "search_knowledge_base" for hits in chunks_returned(call)]
        depth += [rank for hits in searches for rank, hit in enumerate(hits, 1) if hit["chunk_id"] in cited]
    return {"turns": len(steps), "tokens": dict(tokens), "rounds": max(rounds, default=0),
            "tool_calls": max(tool_calls, default=0), "iterations": max(iterations, default=0),
            "steps": max(steps, default=0), "spend": max(spend.values(), default=Decimal(0)),
            "chunks": max(chunks, default=0), "chunk_tokens": max(chunk_tokens, default=0), "depth": max(depth),
            "seconds": max(seconds.values(), default=0.0)}


def above(value: float) -> int:
    return max(1, math.ceil(value * HEADROOM))


def recommend(measured: dict) -> dict[str, tuple[object, object]]:
    """ setting name -> (measured, recommended) """

    rounds = above(measured["rounds"])
    tokens = {f"{agent}_max_tokens_per_call": (used, math.ceil(used * HEADROOM / TOKEN_STEP) * TOKEN_STEP)
              for agent, used in sorted(measured["tokens"].items())}
    # a specialist's own recursion limit has to outlast its round cap (agent and tools per round, then the last
    # reply), so the cap ends a loop on its structured condition before the independent hard cap does
    recursion = max(above(measured["steps"]), 2 * rounds + 2)
    ceiling = (measured["spend"] * Decimal(str(HEADROOM))).quantize(Decimal("0.01"), rounding=ROUND_UP)
    tuned = {**tokens,
             "max_specialist_tool_rounds": (measured["rounds"], rounds),
             "max_tool_invocations_per_turn": (measured["tool_calls"], above(measured["tool_calls"])),
             "max_reviewer_iterations": (measured["iterations"], max(measured["iterations"], MIN_REVIEWER_ITERATIONS)),
             "max_graph_recursion_depth": (measured["steps"], recursion),
             "max_retrieved_chunks_per_turn": (measured["chunks"], above(measured["chunks"])),
             "max_retrieved_tokens_per_turn": (measured["chunk_tokens"], above(measured["chunk_tokens"])),
             "session_cost_ceiling_usd": (measured["spend"], max(ceiling, Decimal("0.01")))}
    if measured["seconds"]:
        tuned["max_turn_wall_clock_seconds"] = (round(measured["seconds"], 1), above(measured["seconds"]))
    if measured["depth"]:
        tuned["retrieval_max_chunks"] = (measured["depth"], above(measured["depth"]))
    return tuned


def env_name(name: str) -> str:
    return "FIELDSIGHT_RETRIEVAL_MAX_CHUNKS" if name == "retrieval_max_chunks" else f"FIELDSIGHT_BOUNDS_{name.upper()}"


def recorded() -> list[dict]:
    """ every analyze and ask run record, oldest first, with every column """

    runs = RunRepository()
    statement = select(runs.table).where(runs.table.c.command.in_(("analyze", "ask"))).order_by(runs.table.c.created_at)
    with runs.engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings().all()]


def drive(folders: list[Path]) -> dict[str, float]:
    """ submit each packet and analyze the incident it makes, through the real graph and KB, as this process's
        analyst; the analyze turn's run id -> its seconds """

    # only a driven run needs the whole system; measuring past runs needs just the database
    from fieldsight.harness.run import wiring
    from fieldsight.security.identity import current_analyst

    analyst, seconds = current_analyst(), {}
    for folder in folders:
        started = time.monotonic()
        submitted = wiring.submit(folder, analyst_id=analyst)
        if submitted["incident_id"] is None:
            print(f"{folder.name}: submit refused ({submitted['refusal']['reason']}), skipped")
            continue
        print(f"{folder.name}: submitted as {submitted['incident_id']} in {time.monotonic() - started:.1f}s")
        started = time.monotonic()
        run = wiring.turn({"command": "analyze", "incident_id": submitted["incident_id"]}, analyst_id=analyst)
        seconds[str(run.run_id)] = time.monotonic() - started
        print(f"{folder.name}: analyzed in {seconds[str(run.run_id)]:.1f}s ({run.refusal['reason'] if run.refusal else 'ok'})")
    return seconds


if __name__ == "__main__":
    seconds = drive(CHOSEN) if CHOSEN else {}
    runs = recorded()
    if CHOSEN:
        runs = [run for run in runs if str(run["run_id"]) in seconds]
    measured = measure(runs, seconds)
    if not measured["turns"]:
        raise SystemExit("no turn ran the graph; run packets with: python script/tune_bounds.py packets <name> ...")

    # a value measured at the cap it ran under was cut off by that cap, so its true need is unknown
    caps = settings.bounds
    print(f"\n{'setting':<36} {'current':>10} {'measured':>10} {'recommended':>12}")
    for name, (seen, value) in recommend(measured).items():
        now = CURRENT_MAX_CHUNKS if name == "retrieval_max_chunks" else getattr(CURRENT, name)
        print(f"{name:<36} {now!s:>10} {seen!s:>10} {value!s:>12}")
    if measured["rounds"] >= caps.max_specialist_tool_rounds:
        print(f"\nsome legs hit the round cap they ran under ({caps.max_specialist_tool_rounds}); their true need is unknown")
    if measured["iterations"] >= caps.max_reviewer_iterations:
        print(f"some turns used every Reviewer iteration ({caps.max_reviewer_iterations}); check whether they approved")
    if measured["depth"] >= settings.retrieval_max_chunks:
        print(f"a cited chunk sat at the last search result ({settings.retrieval_max_chunks}); deeper ones may have been missed")
    if not measured["seconds"]:
        print("turn wall clock not tuned: past run records keep no duration; run packets to measure it")
    if measured["turns"] < MIN_TURNS:
        print(f"only {measured['turns']} graph turns measured; run more incidents before trusting these")

    print(f"\nfrom {measured['turns']} graph turns; set these:")
    for name, (_, value) in recommend(measured).items():
        print(f"{env_name(name)}={value}")
