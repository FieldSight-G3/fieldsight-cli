from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

# the controls 1910.269(l) sets for work on or near exposed energized parts, in paragraph order (l)(1) to (l)(12)
ControlType = Literal[
    "qualified_employees_only",
    "second_employee_present",
    "minimum_approach_distance",
    "insulation",
    "working_position",
    "connection_sequence",
    "conductive_articles_removed",
    "arc_flash_protection",
    "fuse_handling",
    "covered_conductor_precautions",
    "metal_parts_grounded",
    "load_rated_switching",
]


class Proposal(BaseModel):
    """Base model for a worker's proposed finding: a grounded rationale and the chunks it cites."""

    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(
        min_length=1,
        description="What the regulation says and why it applies, citing chunks as [n] in chunk_ids order"
    )
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk ids from search_knowledge_base results that ground the rationale"
    )


class ClassificationProposal(Proposal):
    """The Recordability Worker's proposed finding: recordable or not, and which 300-Log column."""

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


class ReportingProposal(Proposal):
    """The Reportability Worker's proposed finding: reportable or not, on what clock, and any exclusion."""

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


class HazardControlProposal(Proposal):
    """The Hazard Control Worker's proposed control and the 1910.269(l) provision it rests on."""

    outcome: Literal["proposed", "insufficient_data"] = Field(
        description="proposed when paragraph (l) grounds a control; insufficient_data when the corpus supports none"
    )
    control_type: ControlType | None = Field(
        default=None,
        description="The control paragraph (l) requires, only when proposed"
    )
    provision: str | None = Field(
        default=None,
        pattern=r"^(1910\.269\(l\)\(([1-9]|1[0-2])\)(\([a-z0-9]+\))*|Table R-[3-9])$",
        description="The provision the control rests on, e.g. 1910.269(l)(3)(i) or Table R-3; the first chunk_id carries it"
    )
    precedents: list[UUID] = Field(
        default_factory=list,
        description="Optional: incident ids find_similar_incidents returned this run that support the control"
    )

    @model_validator(mode="after")
    def cited_when_proposed(self) -> "HazardControlProposal":
        """ a proposed control can't exist without its type and provision; insufficient_data carries neither """

        proposed = self.outcome == "proposed"
        if proposed != (self.control_type is not None) or proposed != (self.provision is not None):
            raise ValueError("a proposed control needs control_type and provision; insufficient_data takes neither")
        return self
