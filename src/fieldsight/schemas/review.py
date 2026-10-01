from pydantic import BaseModel, ConfigDict, Field, model_validator

from .agents import Worker


class Rejection(BaseModel):
    """One claim in the dossier the Reviewer won't let stand, and the narrower goal to re-dispatch its worker with."""

    model_config = ConfigDict(extra="forbid")

    worker: Worker = Field(
        description="The worker whose leg holds the claim"
    )
    claim: str = Field(
        min_length=1,
        description="The claim, quoted from the leg's proposal"
    )
    problem: str = Field(
        min_length=1,
        description="Why it can't stand: not supported by its cited chunk, uncited, unattributed, or determination-shaped"
    )
    narrowed_goal: str = Field(
        min_length=1,
        description="The narrower goal to re-dispatch the worker with, naming what it must find"
    )


class ReviewVerdict(BaseModel):
    """The Reviewer's verdict on the dossier: approved, or the claims that must be redone."""

    model_config = ConfigDict(extra="forbid")

    approved: bool = Field(
        description="True only when every leg is grounded, cited, attributed and descriptive"
    )
    rejections: list[Rejection] = Field(
        default_factory=list,
        description="One entry per claim that can't stand; empty when approved"
    )

    @model_validator(mode="after")
    def rejected_names_a_claim(self) -> "ReviewVerdict":
        """ an approval carries no rejections, and a rejection names at least one """

        if self.approved == bool(self.rejections):
            raise ValueError("an approved verdict takes no rejections; a rejected one names at least one")
        return self
