""" the agents, named once: the workers the Coordinator dispatches, every agent in the graph, and the Coordinator's plan """

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Worker = Literal["recordability", "reportability", "hazard_control"]
# every agent with its own token limit and checkpointer thread; the nested Worker flattens into the five names
AgentName = Literal["coordinator", Worker, "reviewer"]

class Dispatch(BaseModel):
    """ One worker the coordinator runs, and why. """

    model_config = ConfigDict(extra="forbid")
    worker: Worker = Field(description="The worker to run")
    reason: str = Field(min_length=1, description="The incident fact that makes this worker necessary")

class DispatchPlan(BaseModel):
    """The Coordinator's plan: which workers this incident needs, and why each one. """

    model_config = ConfigDict(extra="forbid")

    dispatches: list[Dispatch] = Field(max_length=3, description="0 to 3 workers; empty when none can help")
    # required, though nullable: an optional field is one a model leaves out, so the quote never arrived
    energized_equipment_quote: str | None = Field(
        description="Required when hazard_control is dispatched: the narrative text, copied exactly, "
                                  "that shows work on or near energized equipment; null if none")

    @model_validator(mode="after")
    def valid_plan(self) -> "DispatchPlan":
        workers = [d.worker for d in self.dispatches]
        if len(workers) != len(set(workers)):
            raise ValueError("each worker is dispatched at most once")
        # a hazard_control dispatch without a quote isn't refused here: the Coordinator drops it as ungrounded and
        # records why, so a missing quote costs that one worker, never the whole plan
        return self

