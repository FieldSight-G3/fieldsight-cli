"""Session isolation: two incidents running concurrently never share state, dossier, or budget.

Covers the layers built so far: the Reviewer's Postgres checkpointer threads and the turn
budget. Extend to the full graph once the Coordinator and top-level graph exist.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from fieldsight.aws import clients
from fieldsight.graph.nodes import review
from fieldsight.graph.nodes.review import reviewer_node
from fieldsight.harness.bounds import BoundsConfig, SessionUsage, TurnUsage, UsageEvent
from fieldsight.harness.bounds_runtime import BoundStopped, TurnBudget


class ApprovingModel:
    """Stateless stand-in for Bedrock, safe to share across threads: approve each new dossier, then stop."""

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if isinstance(messages[-1], HumanMessage):
            return AIMessage("", tool_calls=[{"name": "submit_review", "args": {"verdict": {"approved": True}}, "id": f"submit-{uuid4()}"}])
        return AIMessage("Approved.")


def _dossier(incident: str) -> dict:
    return {"recordability": {
        "task": f"Is {incident} recordable?",
        "proposal": {"outcome": "recordable", "chunk_ids": [f"{incident}-chunk"], "rationale": f"{incident} [1]."},
        "decisions": {},
        "cited": {f"{incident}-chunk": {"chunk_id": f"{incident}-chunk", "doc_id": "CFR-1904", "text": incident}},
    }}


@pytest.fixture
def reviewer(monkeypatch):
    """The Reviewer on the real Postgres checkpointer, rebuilt on a thread-safe model."""
    monkeypatch.setattr(clients, "chat_model", ApprovingModel)
    monkeypatch.setattr(review, "_REVIEWER", None)
    # build once before the threads start: get_reviewer has no lock, and concurrent
    # PostgresSaver.setup() calls race on a fresh database (UniqueViolation creating the tables)
    review.get_reviewer()


def test_two_incidents_reviewed_concurrently_keep_separate_threads(reviewer):
    analyst = f"analyst-{uuid4()}"
    incidents = [f"inc-{uuid4()}", f"inc-{uuid4()}"]
    iterations = 3
    start = Barrier(len(incidents))

    def run(incident: str) -> list[dict]:
        state = {"analyst_id": analyst, "incident": {"incident_id": incident}, "dossier": _dossier(incident)}
        start.wait()
        results = []
        for n in range(iterations):
            results.append(reviewer_node({**state, "review_iterations": n}))
        return results

    with ThreadPoolExecutor(max_workers=len(incidents)) as pool:
        outcomes = dict(zip(incidents, pool.map(run, incidents), strict=True))

    for incident, results in outcomes.items():
        assert [r["review_iterations"] for r in results] == [1, 2, 3]
        assert all(r["reviews"][0].approved for r in results)
        thread = {"configurable": {"thread_id": f"{analyst}:{incident}:reviewer"}}
        messages = review.get_reviewer().get_state(thread).values["messages"]
        # every turn on this thread saw this incident's dossier and nothing else
        assert [m.content for m in messages if isinstance(m, HumanMessage)] == [json.dumps(_dossier(incident))] * iterations


def _budget(incident: int, limits: BoundsConfig) -> TurnBudget:
    usage = SessionUsage(session_id=f"session-{incident}", incident_id=uuid4(), turn=TurnUsage(turn_id=f"turn-{incident}", started_at=datetime.now(UTC)))
    return TurnBudget(usage, limits)


def test_one_incident_exhausting_its_budget_does_not_stop_the_other():
    limits = BoundsConfig(max_tool_invocations_per_turn=40, session_cost_ceiling_usd=Decimal("1.00"))
    spent, healthy = _budget(1, limits), _budget(2, limits)
    start = Barrier(8)

    def spend() -> None:
        start.wait()
        spent.record(UsageEvent(cost_usd=Decimal("0.25")))

    def work() -> int:
        start.wait()
        healthy.reserve_tool_calls(5)
        return 5

    with ThreadPoolExecutor(max_workers=8) as pool:
        spenders = [pool.submit(spend) for _ in range(4)]
        workers = [pool.submit(work) for _ in range(4)]
        for future in spenders:
            future.result()
        assert sum(future.result() for future in workers) == 20

    with pytest.raises(BoundStopped) as caught:
        spent.reserve_tool_calls(1)
    assert caught.value.decision.reason_code == "session_cost_usd"
    assert spent.snapshot().cost_usd == Decimal("1.00")
    assert healthy.snapshot().cost_usd == Decimal(0)
    assert healthy.snapshot().turn.tool_invocations == 20


def test_concurrent_participants_never_overrun_a_shared_turn_budget():
    """Workers in one incident share its budget; racing reservations stop exactly at the cap."""
    limits = BoundsConfig(max_tool_invocations_per_turn=10)
    shared, other = _budget(1, limits), _budget(2, limits)
    start = Barrier(16)

    def reserve(budget: TurnBudget) -> bool:
        start.wait()
        try:
            budget.reserve_tool_calls(1)
        except BoundStopped:
            return False
        return True

    with ThreadPoolExecutor(max_workers=16) as pool:
        granted = list(pool.map(reserve, [shared] * 12 + [other] * 4))

    assert sum(granted[:12]) == 10
    assert all(granted[12:])
    assert shared.snapshot().turn.tool_invocations == 10
    assert other.snapshot().turn.tool_invocations == 4
