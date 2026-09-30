""" the turn's meter: every model call is priced, and the next one is refused once the session can't afford it

    Check-and-stop (requirements §10): before a call, its expected cost (the prompt's estimated tokens plus the full
    output allowance) is added to what the session has already spent; if that passes session_cost_ceiling_usd, or the
    turn's wall clock is spent, the call never starts. After a call, the tokens Bedrock reports are priced and recorded.

    It attaches to every LangChain model call made inside `metered(...)` through a configure hook, so no graph,
    worker or retrieval code has to pass it along.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import Lock
from typing import Any, get_args
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

from ..bounds import AgentName, BoundDecision, BoundsConfig, SessionUsage, UsageEvent
from ..bounds_runtime import BoundStopped, TurnBudget
from .pricing import PricingConfig

# a rough, deliberately generous token estimate for text not yet sent: about four characters per token
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ModelCall:
    """ one priced model call, for the run record (§8: model id, token counts, duration, cost) """

    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    seconds: float


def estimate_tokens(messages: list[list[Any]]) -> int:
    chars = sum(len(str(getattr(message, "content", message))) for batch in messages for message in batch)
    return chars // CHARS_PER_TOKEN + 1


class TurnMeter(BaseCallbackHandler):
    """ prices and gates every chat model call in one turn; raise_error lets a refusal stop the call """

    raise_error = True
    run_inline = True

    def __init__(self, usage: SessionUsage, limits: BoundsConfig, pricing: PricingConfig, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.budget = TurnBudget(usage, limits)
        self.limits = limits
        self.pricing = pricing
        self.clock = clock
        self.calls: list[ModelCall] = []
        self.stopped: BoundDecision | None = None
        self._started: dict[UUID, tuple[str, float]] = {}
        self._lock = Lock()
        # without a configured max_tokens, assume the largest per-call allowance any agent has
        self._default_output = max(limits.token_limit(agent) for agent in get_args(AgentName))

    def expected_cost(self, model_id: str, prompt_tokens: int, max_output_tokens: int) -> Decimal:
        return self.pricing.cost(model_id, prompt_tokens, max_output_tokens)

    def admit(self, model_id: str, prompt_tokens: int, max_output_tokens: int) -> BoundDecision:
        """ whether a call may start: the session can afford its worst case and the turn has time left """

        usage = self.budget.snapshot()
        expected = usage.cost_usd + self.expected_cost(model_id, prompt_tokens, max_output_tokens)
        if expected > self.limits.session_cost_ceiling_usd:
            return BoundDecision(allowed=False, reason_code="session_cost_usd", current=expected, limit=self.limits.session_cost_ceiling_usd)
        elapsed = (self.clock() - usage.turn.started_at).total_seconds()
        if elapsed >= self.limits.max_turn_wall_clock_seconds:
            return BoundDecision(allowed=False, reason_code="turn_wall_clock_seconds", current=elapsed, limit=self.limits.max_turn_wall_clock_seconds)
        return BoundDecision(allowed=True)

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: UUID, **kwargs: Any) -> None:
        metadata = kwargs.get("metadata") or {}
        model_id = (kwargs.get("invocation_params") or {}).get("model") or metadata.get("ls_model_name") or "unknown"
        max_output = metadata.get("ls_max_tokens") or self._default_output
        decision = self.admit(model_id, estimate_tokens(messages), max_output)
        if not decision.allowed:
            with self._lock:
                self.stopped = self.stopped or decision
            raise BoundStopped(decision)
        with self._lock:
            self._started[run_id] = (model_id, time.monotonic())

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            model_id, started = self._started.pop(run_id, ("unknown", time.monotonic()))
        usage = {}
        for batch in response.generations:
            for generation in batch:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or usage
        input_tokens, output_tokens = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        cost = self.pricing.cost(model_id, input_tokens, output_tokens)
        seconds = time.monotonic() - started
        self.budget.record(UsageEvent(cost_usd=cost, elapsed_seconds=0.0))
        with self._lock:
            self.calls.append(ModelCall(model_id, input_tokens, output_tokens, cost, seconds))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        with self._lock:
            self._started.pop(run_id, None)

    @property
    def spent_this_turn(self) -> Decimal:
        with self._lock:
            return sum((call.cost_usd for call in self.calls), Decimal(0))


_active: ContextVar[TurnMeter | None] = ContextVar("fieldsight_turn_meter", default=None)
# every callback manager configured while a meter is active gets it, including nested graphs and tools
register_configure_hook(_active, inheritable=True)


@contextmanager
def metered(usage: SessionUsage, limits: BoundsConfig, pricing: PricingConfig | None = None) -> Iterator[TurnMeter]:
    """ meter every model call made inside the block against this session's budget """

    meter = TurnMeter(usage, limits, pricing or PricingConfig.from_environment())
    token = _active.set(meter)
    try:
        yield meter
    finally:
        _active.reset(token)
