""" a finished agent's transcript as run-record entries: one ModelCall per reply, one ToolInvocation per tool call """

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage

from ..harness.idempotency import idempotency_key
from ..harness.metering.pricing import PricingConfig
from ..schemas.run_records import ModelCall, ToolInvocation

# the same prices the turn meter charges, so the run record and the budget agree
PRICING = PricingConfig.from_settings()


def model_call(agent: str, reply: AIMessage) -> ModelCall:
    """ turns one Bedrock reply into a model call; its model id picks the price, so an unpriced model fails"""

    usage = reply.usage_metadata or {}
    meta = reply.response_metadata
    tokens_in, tokens_out = usage.get("input_tokens", 0), usage.get("output_tokens", 0)

    return ModelCall(
        agent=agent, model_id=meta["model_name"], input_tokens=tokens_in, output_tokens=tokens_out,
        latency_ms=sum(meta.get("metrics", {}).get("latencyMs", [])),     # langchain-aws wraps it in a list
        cost_usd=PRICING.cost(meta["model_name"], tokens_in, tokens_out),
    )

def record(agent: str, messages: list[AnyMessage], session_id: str) -> tuple[list[ToolInvocation], list[ModelCall]]:
    """ tool calls are paired with their results by tool_call_id; session_id is the agent's checkpointer thread

        each call's args_hash is the harness's idempotency key (section 9), so the same call in the same session
        always records the same key
    """

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
                args_hash=str(idempotency_key(session_id, call["name"], call["args"])),
                outcome=None if outcome is None else str(outcome),
            ))
    return tools, calls