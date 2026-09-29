from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RuleId = Literal["R1", "R2", "R3", "R4", "R5"]
LogColumn = Literal["G", "H", "I", "J"]

class RuleDecision(BaseModel):
    """Auditable result produced by one deterministic rule invocation."""

    model_config = ConfigDict(extra="forbid")

    rule_id: RuleId = Field(
        description="Identifier of the deterministic rule that produced this decision"
    )
    outcome: str = Field(
        description="Deterministic outcome produced by the rule"
    )
    inputs: dict[str, Any] = Field(
        description="Complete input values used to calculate the outcome"
    )
    sources: list[str] = Field(
        description="Regulatory or project sources used to define the rule"
    )
    missing_field: str | None = Field(
        default=None,
        description="Required input field that was missing when the outcome is insufficient_data"
    )
    deadline: datetime | None = Field(
        default=None,
        description="Calculated OSHA reporting deadline when applicable"
    )
    log_column: LogColumn | None = Field(
        default=None,
        description="Selected OSHA 300 Log outcome column when applicable"
    )
    day_count: int | None = Field(
        default=None,
        ge=0,
        description="Combined and capped day count used for OSHA 300 Log classification"
    )
    exclusion: str | None = Field(
        default=None,
        description="The 1904.39(b)(10) or (b)(11) exclusion that made an event not reportable, when one did"
    )