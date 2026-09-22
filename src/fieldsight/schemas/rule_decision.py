from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


RuleId = Literal["R1", "R2", "R3", "R4", "R5"]
LogColumn = Literal["G", "H", "I", "J"]


class RuleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: RuleId
    outcome: str
    inputs: dict[str, Any]
    sources: list[str]

    missing_field: str | None = None
    deadline: datetime | None = None
    log_column: LogColumn | None = None
    day_count: int | None = None