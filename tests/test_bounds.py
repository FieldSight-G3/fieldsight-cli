"""Check-and-stop budgets, including cost across ask turns and isolation."""

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError

from fieldsight.harness.bounds import (
    AgentName,
    BoundsConfig,
    LegKind,
    LegRequest,
    SessionUsage,
    TurnUsage,
    UsageEvent,
    preflight,
    record_usage,
    start_turn,
)

CASE_A = UUID("00000000-0000-0000-0000-000000000001")
CASE_B = UUID("00000000-0000-0000-0000-000000000002")
ORIGIN = datetime(2026, 9, 24, 12, tzinfo=UTC)


def session(*, incident_id: UUID = CASE_A, session_id: str = "session-a") -> SessionUsage:
    return SessionUsage(session_id=session_id, incident_id=incident_id, turn=TurnUsage(turn_id="analyze-1", started_at=ORIGIN))


class BoundsTests(unittest.TestCase):
    def test_each_agent_has_a_hard_total_token_cap(self) -> None:
        limits = BoundsConfig()
        agents: tuple[AgentName, ...] = ("coordinator", "recordability", "reportability", "hazard_control", "reviewer")
        for agent in agents:
            with self.subTest(agent=agent):
                cap = limits.token_limit(agent)
                self.assertTrue(preflight(session(), limits, LegRequest(kind="model", agent=agent, prompt_tokens=cap - 1, requested_output_tokens=1), now=ORIGIN).allowed)
                self.assertEqual(preflight(session(), limits, LegRequest(kind="model", agent=agent, prompt_tokens=cap, requested_output_tokens=1), now=ORIGIN).reason_code, "agent_tokens_per_call")

    def test_tool_and_retrieval_counts_stop_before_an_extra_call(self) -> None:
        limits = BoundsConfig(max_tool_invocations_per_turn=2)
        used = record_usage(session(), UsageEvent(tool_invocations=2))
        kinds: tuple[LegKind, ...] = ("tool", "retrieval")
        for kind in kinds:
            with self.subTest(kind=kind):
                self.assertEqual(preflight(used, limits, LegRequest(kind=kind), now=ORIGIN).reason_code, "tool_invocations")
        self.assertEqual(session().turn.tool_invocations, 0)

    def test_graph_and_reviewer_loops_have_independent_hard_caps(self) -> None:
        limits = BoundsConfig(max_graph_recursion_depth=3, max_reviewer_iterations=1)
        used = record_usage(session(), UsageEvent(graph_steps=3, reviewer_iterations=1))
        self.assertEqual(preflight(used, limits, LegRequest(kind="graph"), now=ORIGIN).reason_code, "graph_recursion_depth")
        self.assertEqual(preflight(used, limits, LegRequest(kind="reviewer"), now=ORIGIN).reason_code, "reviewer_iterations")

    def test_retrieval_chunk_and_token_caps_include_the_next_request(self) -> None:
        limits = BoundsConfig(max_retrieved_chunks_per_turn=3, max_retrieved_tokens_per_turn=100)
        used = record_usage(session(), UsageEvent(retrieved_chunks=2, retrieved_tokens=80, tool_invocations=1))
        self.assertTrue(preflight(used, limits, LegRequest(kind="retrieval", expected_retrieved_chunks=1, expected_retrieved_tokens=20), now=ORIGIN).allowed)
        self.assertEqual(preflight(used, limits, LegRequest(kind="retrieval", expected_retrieved_chunks=2), now=ORIGIN).reason_code, "retrieved_chunks")
        self.assertEqual(preflight(used, limits, LegRequest(kind="retrieval", expected_retrieved_tokens=21), now=ORIGIN).reason_code, "retrieved_tokens")

    def test_wall_clock_and_session_cost_stop_new_legs(self) -> None:
        limits = BoundsConfig(max_turn_wall_clock_seconds=10, session_cost_ceiling_usd=Decimal("1.00"))
        slow = record_usage(session(), UsageEvent(elapsed_seconds=10))
        self.assertEqual(preflight(slow, limits, LegRequest(kind="model", agent="reviewer", prompt_tokens=0, requested_output_tokens=1), now=ORIGIN).reason_code, "turn_wall_clock_seconds")
        self.assertEqual(preflight(session(), limits, LegRequest(kind="tool"), now=ORIGIN + timedelta(seconds=10)).reason_code, "turn_wall_clock_seconds")
        spent = record_usage(session(), UsageEvent(cost_usd=Decimal("1.00")))
        self.assertEqual(preflight(spent, limits, LegRequest(kind="tool"), now=ORIGIN).reason_code, "session_cost_usd")

    def test_ask_resets_turn_counts_but_keeps_session_cost(self) -> None:
        limits = BoundsConfig(session_cost_ceiling_usd=Decimal("1.00"))
        analyze = record_usage(session(), UsageEvent(cost_usd=Decimal("0.60"), tool_invocations=12))
        ask = start_turn(analyze, "ask-2", started_at=ORIGIN + timedelta(minutes=1))
        self.assertEqual(ask.turn.tool_invocations, 0)
        self.assertEqual(ask.cost_usd, Decimal("0.60"))
        ask = record_usage(ask, UsageEvent(cost_usd=Decimal("0.40")))
        self.assertEqual(preflight(ask, limits, LegRequest(kind="tool"), now=ORIGIN + timedelta(minutes=1)).reason_code, "session_cost_usd")
        with self.assertRaises(ValueError):
            start_turn(ask, "ask-2")

    def test_two_incidents_do_not_share_usage(self) -> None:
        a = session()
        b = session(incident_id=CASE_B, session_id="session-b")
        a = record_usage(a, UsageEvent(cost_usd=Decimal("5.00"), tool_invocations=12))
        self.assertEqual(preflight(a, BoundsConfig(), LegRequest(kind="tool"), now=ORIGIN).reason_code, "session_cost_usd")
        self.assertTrue(preflight(b, BoundsConfig(), LegRequest(kind="tool"), now=ORIGIN).allowed)
        self.assertEqual(b.cost_usd, Decimal(0))

    def test_environment_overrides_and_invalid_requests(self) -> None:
        values = {"FIELDSIGHT_BOUNDS_SESSION_COST_CEILING_USD": "2.25", "FIELDSIGHT_BOUNDS_MAX_REVIEWER_ITERATIONS": "3"}
        limits = BoundsConfig.from_environment(values)
        self.assertEqual(limits.session_cost_ceiling_usd, Decimal("2.25"))
        self.assertEqual(limits.max_reviewer_iterations, 3)
        with self.assertRaises(ValidationError):
            BoundsConfig.from_environment({"FIELDSIGHT_BOUNDS_MAX_REVIEWER_ITERATIONS": "0"})
        with self.assertRaises(ValidationError):
            LegRequest(kind="model")


if __name__ == "__main__":
    unittest.main()
