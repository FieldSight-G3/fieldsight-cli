from datetime import datetime

from pydantic import BaseModel, ConfigDict

from fieldsight.schemas.rule_decision import RuleDecision


class RuleInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str
    recorded_at: datetime
    decision: RuleDecision