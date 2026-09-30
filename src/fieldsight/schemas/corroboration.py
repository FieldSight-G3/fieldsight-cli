from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Corroboration = Literal["corroborates", "contradicts", "inconclusive"]


class PhotoVerdict(BaseModel):
    """What one photograph shows, judged against the supervisor's narrative."""

    model_config = ConfigDict(extra="forbid")

    verdict: Corroboration = Field(
        description="corroborates: the photo is consistent with the narrative; contradicts: it shows something "
                    "the narrative can't be true alongside; inconclusive: it can't be judged either way"
    )
    observation: str = Field(
        min_length=1,
        description="What the photo visibly shows that bears on the incident, without naming anyone"
    )
    reason: str = Field(
        min_length=1,
        description="Which narrative statement the observation supports or conflicts with, and why"
    )
