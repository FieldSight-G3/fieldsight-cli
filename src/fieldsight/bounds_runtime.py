"""Turn-scoped check-and-stop budget shared by concurrent agent participants.

The caller creates this from persisted SessionUsage and passes the same object
to the Coordinator, workers, Reviewer, and tool dispatcher for one turn.
"""

from __future__ import annotations

from threading import RLock

from fieldsight.bounds import (
    BoundDecision,
    BoundsConfig,
    LegRequest,
    SessionUsage,
    UsageEvent,
    preflight,
    record_usage,
)
from fieldsight.errors import FieldSightError


class BoundStopped(FieldSightError, RuntimeError):
    """A budget is spent; still a RuntimeError for existing handlers."""

    def __init__(self, decision: BoundDecision) -> None:
        self.decision = decision
        super().__init__(f"Budget stopped: {decision.reason_code} ({decision.current}/{decision.limit})")


class TurnBudget:
    def __init__(self, usage: SessionUsage, limits: BoundsConfig) -> None:
        self._usage = usage
        self._limits = limits
        self._lock = RLock()

    def check(self, request: LegRequest) -> None:
        """Stop before a model or graph leg starts."""
        with self._lock:
            decision = preflight(self._usage, self._limits, request)
            if not decision.allowed:
                raise BoundStopped(decision)

    def reserve_tool_calls(self, count: int) -> None:
        """Reserve every call in a ToolNode batch before dispatching any of them."""
        if count < 0:
            raise ValueError("Tool call count cannot be negative")
        with self._lock:
            candidate = self._usage
            for _ in range(count):
                decision = preflight(candidate, self._limits, LegRequest(kind="tool"))
                if not decision.allowed:
                    raise BoundStopped(decision)
                candidate = record_usage(candidate, UsageEvent(tool_invocations=1))
            self._usage = candidate

    def reserve_graph_step(self) -> None:
        """Count a graph node before starting it, even with parallel workers."""
        with self._lock:
            decision = preflight(self._usage, self._limits, LegRequest(kind="graph"))
            if not decision.allowed:
                raise BoundStopped(decision)
            self._usage = record_usage(self._usage, UsageEvent(graph_steps=1))

    def record(self, event: UsageEvent) -> None:
        """Add measured model cost, tokens, retrieval counts, or elapsed time."""
        with self._lock:
            self._usage = record_usage(self._usage, event)

    def snapshot(self) -> SessionUsage:
        """Return the final usage for the repository to persist with the run."""
        with self._lock:
            return self._usage.model_copy(deep=True)
