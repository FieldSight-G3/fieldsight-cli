from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.schemas.rule_decision import LogColumn

# the narrow definitions of 1904.39(b)(10) and (b)(11) that take an event off the reporting clock
Exclusion = Literal[
    "observation_only",
    "diagnostic_testing_only",
    "avulsion",
    "enucleation",
    "degloving",
    "scalping",
    "severed_ear",
    "broken_tooth",
    "chipped_tooth",
]


class ClassificationProposal(BaseModel):
    """The Recordability Worker's proposed finding: recordable or not, and which 300-Log column."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["recordable", "not_recordable", "insufficient_data"] = Field(
        description="The R1 outcome recorded this run; never decided by the model"
    )
    log_column: LogColumn | None = Field(
        default=None,
        description="The R4 column (G, H, I or J) when the case is recordable"
    )
    day_count: int | None = Field(
        default=None,
        ge=0,
        description="The R4 capped day count when the case is recordable"
    )
    missing_field: str | None = Field(
        default=None,
        description="The field R1 named when it returned insufficient_data, or R4 named when it couldn't pick a column"
    )
    rationale: str = Field(
        min_length=1,
        description="What the regulation says and why it applies, citing chunks as [n] in chunk_ids order"
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk ids from search_knowledge_base results that ground the rationale"
    )


class ReportingProposal(BaseModel):
    """The Reportability Worker's proposed finding: reportable or not, on what clock, and any exclusion."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["reportable", "not_reportable", "insufficient_data"] = Field(
        description="The R2 outcome recorded this run; never decided by the model"
    )
    clock_hours: Literal[8, 24] | None = Field(
        default=None,
        description="8 for a fatality, 24 for hospitalization, amputation or loss of an eye; only when reportable"
    )
    deadline: datetime | None = Field(
        default=None,
        description="The R2 reporting deadline when reportable"
    )
    exclusion: Exclusion | None = Field(
        default=None,
        description="The 1904.39(b)(10) or (b)(11) exclusion that takes the event off the clock, when one applies"
    )
    missing_field: str | None = Field(
        default=None,
        description="The field R2 named when the outcome is insufficient_data"
    )
    rationale: str = Field(
        min_length=1,
        description="What the regulation says and why it applies, citing chunks as [n] in chunk_ids order"
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk ids from search_knowledge_base results that ground the rationale"
    )
