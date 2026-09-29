""" a finished agent's transcript as run-record entries: one ModelCall per reply, one ToolInvocation per tool call """

import hashlib

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from ..config import settings
from ..harness.idempotency import canonicalize
from ..schemas.run_records import ModelCall, ToolInvocation

PRICES = {settings.bedrock_model_id: settings.reasoning_price, settings.bedrock_fast_model_id: settings.fast_price}


def model_call(agent: str, reply: AIMessage) -> ModelCall:
    """ one Bedrock reply; its model id picks the price, so an unpriced model fails"""

    usage = reply.usage_metadata or {}
    meta = reply.response_metadata
    price = PRICES[meta["model_name"]]
    tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)

    return ModelCall(
        agent=agent, model_id=meta["model_name"], input_tokens=tokens_in, output_tokens=tokens_out,
        latency_ms=sum(meta.get("metrics", {}).get("latencyMs", [])),     # langchain-aws wraps it in a list
        cost_usd=(tokens_in * price.input_per_mtok + tokens_out * price.output_per_mtok) / 1_000_000,
    )

def record(agent: str, messages: list[AnyMessage]) -> tuple[list[ToolInvocation], list[ModelCall]]:
    """ tool calls are paired with their results by tool_call_id """

    results = {m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)}
    tools, calls = [], []

    for m in messages:
        if not isinstance(m, AIMessage):
            continue
        calls.append(model_call(agent, m))
        for call in m.tool_calls:
            outcome = results.get(call["id"])
            tools.append(ToolInvocation(
                agent=agent, tool=call["name"], args=call["args"],
                args_hash=hashlib.sha256(canonicalize(call["args"]).encode()).hexdigest(),
                outcome=None if outcome is None else str(outcome),
            ))
    return tools, calls