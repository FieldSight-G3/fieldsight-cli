"""The turn meter prices every model call from Bedrock's token counts and refuses the next call once it can't be afforded."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda, RunnableParallel

from fieldsight.config import ModelPrice
from fieldsight.harness.bounds import BoundsConfig, SessionUsage, TurnUsage
from fieldsight.harness.bounds_runtime import BoundStopped
from fieldsight.harness.metering.meter import metered
from fieldsight.harness.metering.pricing import PricingConfig

START = datetime(2026, 9, 29, 12, tzinfo=UTC)
# the stand-in model and its price; the dollar amounts below are this price at the fake token counts
PRICING = PricingConfig(prices={"deepseek.v3.2": ModelPrice(input_per_mtok=Decimal("0.62"), output_per_mtok=Decimal("1.85"))})


class FakeBedrock:
    """ stands in for the Bedrock runtime client: every Converse call reports the same token usage """

    def __init__(self, input_tokens: int = 6000, output_tokens: int = 800) -> None:
        self.calls = 0
        self.usage = {"inputTokens": input_tokens, "outputTokens": output_tokens, "totalTokens": input_tokens + output_tokens}

    def converse(self, **kwargs):
        self.calls += 1
        return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}, "usage": self.usage,
                "stopReason": "end_turn", "metrics": {"latencyMs": 5}, "ResponseMetadata": {}}


def model(client: FakeBedrock, max_tokens: int = 1000) -> ChatBedrockConverse:
    chat = ChatBedrockConverse(model_id="deepseek.v3.2", region_name="us-east-1", max_tokens=max_tokens)
    chat.client = client
    return chat


def session(spent: str = "0", started: datetime | None = None) -> SessionUsage:
    return SessionUsage(session_id="s-1", incident_id=UUID(int=1), cost_usd=Decimal(spent),
                        turn=TurnUsage(turn_id="t-1", started_at=started or datetime.now(UTC)))


def test_each_call_is_priced_from_the_tokens_bedrock_reports():
    bedrock = FakeBedrock(6000, 800)

    with metered(session(), BoundsConfig(), PRICING) as meter:
        model(bedrock).invoke([HumanMessage("Is this recordable?")])
        model(bedrock).invoke([HumanMessage("And reportable?")])

    assert bedrock.calls == 2
    assert [(c.model_id, c.input_tokens, c.output_tokens, c.cost_usd) for c in meter.calls] == [("deepseek.v3.2", 6000, 800, Decimal("0.00520"))] * 2
    assert meter.spent_this_turn == Decimal("0.01040")
    assert meter.budget.snapshot().cost_usd == Decimal("0.01040")


def test_a_call_the_session_cannot_afford_never_starts():
    bedrock = FakeBedrock()
    # $4.999 already spent of a $5.00 ceiling: the next call's worst case (prompt + 1000 output tokens) doesn't fit
    with metered(session(spent="4.999"), BoundsConfig(), PRICING) as meter, pytest.raises(BoundStopped) as stopped:
        model(bedrock, max_tokens=1000).invoke([HumanMessage("x" * 4000)])

    assert bedrock.calls == 0
    assert stopped.value.decision.reason_code == "session_cost_usd"
    assert meter.stopped is not None and meter.calls == []


def test_spending_accumulates_until_the_next_call_is_refused():
    bedrock = FakeBedrock(6000, 800)
    # after two calls $0.0104 is spent; a third call's worst case (~$0.0017) would pass $0.012
    limits = BoundsConfig(session_cost_ceiling_usd=Decimal("0.012"))

    with metered(session(), limits, PRICING) as meter:
        model(bedrock, max_tokens=900).invoke([HumanMessage("first")])
        model(bedrock, max_tokens=900).invoke([HumanMessage("second")])
        with pytest.raises(BoundStopped):
            model(bedrock, max_tokens=900).invoke([HumanMessage("third")])

    assert bedrock.calls == 2
    assert meter.spent_this_turn == Decimal("0.01040")


def test_a_spent_turn_clock_refuses_the_next_call():
    bedrock = FakeBedrock()
    limits = BoundsConfig(max_turn_wall_clock_seconds=120)

    with metered(session(started=START), limits, PRICING) as meter, pytest.raises(BoundStopped) as stopped:
        meter.clock = lambda: START + timedelta(seconds=121)
        model(bedrock).invoke([HumanMessage("late")])

    assert stopped.value.decision.reason_code == "turn_wall_clock_seconds" and bedrock.calls == 0


def test_calls_nested_in_chains_and_parallel_branches_are_metered():
    bedrock = FakeBedrock(1000, 100)
    ask = RunnableLambda(lambda question: model(bedrock).invoke([HumanMessage(question)]))
    fan_out = RunnableParallel(recordability=ask, reportability=ask)

    with metered(session(), BoundsConfig(), PRICING) as meter:
        fan_out.invoke("the incident")

    assert bedrock.calls == 2 and len(meter.calls) == 2


def test_nothing_is_metered_outside_a_turn():
    bedrock = FakeBedrock()
    with metered(session(), BoundsConfig(), PRICING) as meter:
        pass

    model(bedrock).invoke([HumanMessage("after the turn")])

    assert bedrock.calls == 1 and meter.calls == []
