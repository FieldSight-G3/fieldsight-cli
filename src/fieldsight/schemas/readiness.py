from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ReadinessLabel = Literal["policy_question", "classify", "follow_up", "action", "out_of_scope"]


class ReadinessClassification(BaseModel):
    """The fast model's label for an analyst's question; a deterministic check runs after it regardless."""

    model_config = ConfigDict(extra="forbid")

    label: ReadinessLabel = Field(
        description="policy_question, classify, action or out_of_scope, as the brief defines them"
    )
    reason: str = Field(
        min_length=1,
        description="One sentence on why the question has this label"
    )
