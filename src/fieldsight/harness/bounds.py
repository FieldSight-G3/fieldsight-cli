"""Typed, side-effect-free budget checks for one incident session.

The graph and tool dispatcher call preflight before each leg and record_usage
after it. Persist SessionUsage between turns; start_turn resets only turn counts.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from os import environ
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..schemas.agents import AgentName

LegKind = Literal["model", "tool", "retrieval", "graph", "reviewer"]
BoundName = Literal[
    "session_cost_usd", "turn_wall_clock_seconds", "agent_tokens_per_call",
    "tool_invocations", "graph_recursion_depth", "retrieved_chunks",
    "retrieved_tokens", "reviewer_iterations",
]


class BoundsConfig(BaseModel):
    """Initial limits; tune them with measured traces before deployment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    coordinator_max_tokens_per_call: int = Field(default=4096, gt=0)
    recordability_max_tokens_per_call: int = Field(default=6144, gt=0)
    reportability_max_tokens_per_call: int = Field(default=6144, gt=0)
    hazard_control_max_tokens_per_call: int = Field(default=6144, gt=0)
    reviewer_max_tokens_per_call: int = Field(default=4096, gt=0)
    max_tool_invocations_per_turn: int = Field(default=54, gt=0)
    max_specialist_tool_rounds: int = Field(default=10, gt=0)
    max_graph_recursion_depth: int = Field(default=32, gt=0)
    max_reviewer_iterations: int = Field(default=2, gt=0)
    max_retrieved_chunks_per_turn: int = Field(default=113, gt=0)
    max_retrieved_tokens_per_turn: int = Field(default=25767, gt=0)
    max_turn_wall_clock_seconds: float = Field(default=300.0, gt=0)
    http_timeout_seconds: float = Field(default=20.0, gt=0)
    sts_timeout_seconds: float = Field(default=3.0, gt=0)
    session_cost_ceiling_usd: Decimal = Field(default=Decimal("5.00"), gt=0)
    db_write_max_attempts: int = Field(default=3, gt=0)
    db_write_backoff_seconds: float = Field(default=0.2, ge=0)

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> BoundsConfig:
        """Read FIELDSIGHT_BOUNDS_* values from the current environment."""
        source = environ if values is None else values
        overrides = {
            field: source[f"FIELDSIGHT_BOUNDS_{field.upper()}"]
            for field in cls.model_fields
            if f"FIELDSIGHT_BOUNDS_{field.upper()}" in source
        }
        return cls.model_validate(overrides)

    def token_limit(self, agent: AgentName) -> int:
        limits = {
            "coordinator": self.coordinator_max_tokens_per_call,
            "recordability": self.recordability_max_tokens_per_call,
            "reportability": self.reportability_max_tokens_per_call,
            "hazard_control": self.hazard_control_max_tokens_per_call,
            "reviewer": self.reviewer_max_tokens_per_call,
        }
        return limits[agent]


class TurnUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_invocations: int = Field(default=0, ge=0)
    graph_steps: int = Field(default=0, ge=0)
    reviewer_iterations: int = Field(default=0, ge=0)
    retrieved_chunks: int = Field(default=0, ge=0)
    retrieved_tokens: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)

    @model_validator(mode="after")
    def timezone_is_known(self) -> TurnUsage:
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("Turn start timestamp must have a timezone")
        return self


class SessionUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(min_length=1)
    incident_id: UUID
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    turn: TurnUsage


class LegRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: LegKind
    agent: AgentName | None = None
    prompt_tokens: int | None = Field(default=None, ge=0)
    requested_output_tokens: int | None = Field(default=None, gt=0)
    expected_retrieved_chunks: int = Field(default=0, ge=0)
    expected_retrieved_tokens: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def consistent_leg(self) -> LegRequest:
        if self.kind == "model" and (self.agent is None or self.prompt_tokens is None or self.requested_output_tokens is None):
            raise ValueError("A model leg needs an agent, prompt token count, and output token cap")
        if self.kind != "model" and (self.agent is not None or self.prompt_tokens is not None or self.requested_output_tokens is not None):
            raise ValueError("Only a model leg accepts an agent and token counts")
        if self.kind != "retrieval" and (self.expected_retrieved_chunks or self.expected_retrieved_tokens):
            raise ValueError("Only a retrieval leg accepts expected chunks or tokens")
        return self


class UsageEvent(BaseModel):
    """Measured usage after a completed call or graph step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    tool_invocations: int = Field(default=0, ge=0)
    graph_steps: int = Field(default=0, ge=0)
    reviewer_iterations: int = Field(default=0, ge=0)
    retrieved_chunks: int = Field(default=0, ge=0)
    retrieved_tokens: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)


class BoundDecision(BaseModel):
    """A structured stop reason for the run record and the analyst."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reason_code: BoundName | None = None
    current: Decimal | float | int | None = None
    limit: Decimal | float | int | None = None


def start_turn(usage: SessionUsage, turn_id: str, *, started_at: datetime | None = None) -> SessionUsage:
    """Carry the session dollar total into a new analyze or ask turn."""
    if usage.turn.turn_id == turn_id:
        raise ValueError("New turn must have a new turn_id")
    return SessionUsage(session_id=usage.session_id, incident_id=usage.incident_id, cost_usd=usage.cost_usd, turn=TurnUsage(turn_id=turn_id, started_at=started_at or datetime.now(UTC)))


def record_usage(usage: SessionUsage, event: UsageEvent) -> SessionUsage:
    """Accumulate actual usage; the next preflight checks the spent totals."""
    turn = usage.turn
    return SessionUsage(
        session_id=usage.session_id, incident_id=usage.incident_id,
        cost_usd=usage.cost_usd + event.cost_usd,
        turn=TurnUsage(
            turn_id=turn.turn_id,
            started_at=turn.started_at,
            tool_invocations=turn.tool_invocations + event.tool_invocations,
            graph_steps=turn.graph_steps + event.graph_steps,
            reviewer_iterations=turn.reviewer_iterations + event.reviewer_iterations,
            retrieved_chunks=turn.retrieved_chunks + event.retrieved_chunks,
            retrieved_tokens=turn.retrieved_tokens + event.retrieved_tokens,
            elapsed_seconds=turn.elapsed_seconds + event.elapsed_seconds,
        ),
    )


def preflight(usage: SessionUsage, limits: BoundsConfig, request: LegRequest, *, now: datetime | None = None) -> BoundDecision:
    """Refuse to start the next leg after any applicable budget is spent."""
    if usage.cost_usd >= limits.session_cost_ceiling_usd:
        return _stop("session_cost_usd", usage.cost_usd, limits.session_cost_ceiling_usd)
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Current timestamp must have a timezone")
    elapsed = max(usage.turn.elapsed_seconds, (clock - usage.turn.started_at).total_seconds())
    if elapsed >= limits.max_turn_wall_clock_seconds:
        return _stop("turn_wall_clock_seconds", elapsed, limits.max_turn_wall_clock_seconds)
    if request.kind == "model":
        assert request.agent is not None and request.prompt_tokens is not None and request.requested_output_tokens is not None
        limit = limits.token_limit(request.agent)
        requested_total = request.prompt_tokens + request.requested_output_tokens
        if requested_total > limit:
            return _stop("agent_tokens_per_call", requested_total, limit)
    if request.kind in ("tool", "retrieval") and usage.turn.tool_invocations + 1 > limits.max_tool_invocations_per_turn:
        return _stop("tool_invocations", usage.turn.tool_invocations, limits.max_tool_invocations_per_turn)
    if request.kind == "graph" and usage.turn.graph_steps + 1 > limits.max_graph_recursion_depth:
        return _stop("graph_recursion_depth", usage.turn.graph_steps, limits.max_graph_recursion_depth)
    if request.kind == "reviewer" and usage.turn.reviewer_iterations + 1 > limits.max_reviewer_iterations:
        return _stop("reviewer_iterations", usage.turn.reviewer_iterations, limits.max_reviewer_iterations)
    if request.kind == "retrieval":
        if usage.turn.retrieved_chunks + request.expected_retrieved_chunks > limits.max_retrieved_chunks_per_turn:
            return _stop("retrieved_chunks", usage.turn.retrieved_chunks, limits.max_retrieved_chunks_per_turn)
        if usage.turn.retrieved_tokens + request.expected_retrieved_tokens > limits.max_retrieved_tokens_per_turn:
            return _stop("retrieved_tokens", usage.turn.retrieved_tokens, limits.max_retrieved_tokens_per_turn)
        if usage.turn.retrieved_chunks >= limits.max_retrieved_chunks_per_turn:
            return _stop("retrieved_chunks", usage.turn.retrieved_chunks, limits.max_retrieved_chunks_per_turn)
        if usage.turn.retrieved_tokens >= limits.max_retrieved_tokens_per_turn:
            return _stop("retrieved_tokens", usage.turn.retrieved_tokens, limits.max_retrieved_tokens_per_turn)
    return BoundDecision(allowed=True)


def _stop(reason: BoundName, current: Decimal | float, limit: Decimal | float) -> BoundDecision:
    return BoundDecision(allowed=False, reason_code=reason, current=current, limit=limit)
