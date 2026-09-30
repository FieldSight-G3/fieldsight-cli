from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from fieldsight.schemas.rule_decision import RuleDecision


class RuleInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    recorded_at: datetime
    decision: RuleDecision

class ToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    tool: str
    args: dict
    args_hash: str
    outcome: str | None

class ModelCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: Decimal