from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.schemas.rule_decision import RuleDecision


class RuleInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    recorded_at: datetime
    decision: RuleDecision


class RuleRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    started_at: datetime
    completed_at: datetime | None = None
    invocations: list[RuleInvocation] = Field(default_factory=list)