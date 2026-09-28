"""Ensure a shared turn budget reserves tool batches without partial dispatch."""

import unittest
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fieldsight.harness.bounds import (
    BoundsConfig,
    LegRequest,
    SessionUsage,
    TurnUsage,
    UsageEvent,
)
from fieldsight.harness.bounds_runtime import BoundStopped, TurnBudget


class TurnBudgetTests(unittest.TestCase):
    def budget(self) -> TurnBudget:
        usage = SessionUsage(session_id="session-a", incident_id=UUID(int=1), turn=TurnUsage(turn_id="turn-a", started_at=datetime.now(UTC)))
        return TurnBudget(usage, BoundsConfig(max_tool_invocations_per_turn=2, session_cost_ceiling_usd=Decimal("1.00")))

    def test_batch_is_all_or_nothing(self) -> None:
        budget = self.budget()
        budget.reserve_tool_calls(1)
        with self.assertRaises(BoundStopped) as caught:
            budget.reserve_tool_calls(2)
        self.assertEqual(caught.exception.decision.reason_code, "tool_invocations")
        self.assertEqual(budget.snapshot().turn.tool_invocations, 1)
        budget.reserve_tool_calls(1)
        self.assertEqual(budget.snapshot().turn.tool_invocations, 2)

    def test_session_cost_stops_the_next_leg(self) -> None:
        budget = self.budget()
        budget.record(UsageEvent(cost_usd=Decimal("1.00")))
        with self.assertRaises(BoundStopped) as caught:
            budget.check(LegRequest(kind="model", agent="reviewer", prompt_tokens=1, requested_output_tokens=1))
        self.assertEqual(caught.exception.decision.reason_code, "session_cost_usd")

    def test_input_usage_is_not_mutated(self) -> None:
        original = SessionUsage(session_id="session-a", incident_id=UUID(int=1), turn=TurnUsage(turn_id="turn-a", started_at=datetime.now(UTC)))
        budget = TurnBudget(original, BoundsConfig())
        budget.reserve_tool_calls(1)
        self.assertEqual(original.turn.tool_invocations, 0)
        self.assertEqual(budget.snapshot().turn.tool_invocations, 1)

    def test_graph_steps_stop_before_the_next_node(self) -> None:
        usage = SessionUsage(session_id="session-a", incident_id=UUID(int=1), turn=TurnUsage(turn_id="turn-a", started_at=datetime.now(UTC)))
        budget = TurnBudget(usage, BoundsConfig(max_graph_recursion_depth=1))
        budget.reserve_graph_step()
        with self.assertRaises(BoundStopped) as caught:
            budget.reserve_graph_step()
        self.assertEqual(caught.exception.decision.reason_code, "graph_recursion_depth")
        self.assertEqual(budget.snapshot().turn.graph_steps, 1)


if __name__ == "__main__":
    unittest.main()
