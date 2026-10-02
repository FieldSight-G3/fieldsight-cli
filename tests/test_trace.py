""" record turns a finished agent's transcript into its run-record entries """

from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from fieldsight.config import ModelPrice
from fieldsight.graph import trace
from fieldsight.harness.idempotency import idempotency_key
from fieldsight.harness.metering.pricing import PricingConfig, UnpricedModel

# the agent's checkpointer thread: (analyst, incident, participant)
SESSION = "analyst-1:inc-1:recordability"


@pytest.fixture(autouse=True)
def priced(monkeypatch):
    # a known price, so the cost below doesn't depend on whatever .env holds
    monkeypatch.setattr(trace, "PRICING", PricingConfig(prices={"test-model": ModelPrice(input_per_mtok=Decimal(3), output_per_mtok=Decimal(15))}))


def reply(tool_calls=(), model="test-model"):
    return AIMessage(content="", tool_calls=list(tool_calls),
                     usage_metadata={"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200},
                     response_metadata={"model_name": model, "metrics": {"latencyMs": [500]}})


def test_pairs_each_tool_call_with_its_result():
    messages = [
        HumanMessage("task"),
        reply([{"name": "evaluate_rule", "args": {"rule_id": "R4"}, "id": "t1"},
               {"name": "search_knowledge_base", "args": {"query": "days away"}, "id": "t2"}]),
        ToolMessage("column H", tool_call_id="t1"),
        reply(),
    ]
    tools, calls = trace.record("recordability", messages, SESSION)

    assert [t.tool for t in tools] == ["evaluate_rule", "search_knowledge_base"]
    assert [t.outcome for t in tools] == ["column H", None]     # t2 was requested but never ran
    assert len(calls) == 2


def test_each_tool_call_is_keyed_by_the_harness_idempotency_key():
    first = reply([{"name": "evaluate_rule", "args": {"rule_id": "R4"}, "id": "t1"}])
    retry = reply([{"name": "evaluate_rule", "args": {"rule_id": "R4"}, "id": "t9"}])

    (once,), _ = trace.record("recordability", [first], SESSION)
    (again,), _ = trace.record("recordability", [retry], SESSION)
    (elsewhere,), _ = trace.record("recordability", [first], "analyst-2:inc-1:recordability")

    assert once.args_hash == str(idempotency_key(SESSION, "evaluate_rule", {"rule_id": "R4"}))
    # the same call in the same session gets the same key, whatever its tool-call id; another session's differs
    assert again.args_hash == once.args_hash
    assert elsewhere.args_hash != once.args_hash


def test_prices_tokens_and_reads_latency():
    (call,) = trace.record("coordinator", [reply()], SESSION)[1]

    assert call.cost_usd == Decimal("0.006")     # (1000 × $3 + 200 × $15) / 1M
    assert call.latency_ms == 500


def test_unpriced_model_fails_loudly():
    with pytest.raises(UnpricedModel):
        trace.record("coordinator", [reply(model="unpriced")], SESSION)