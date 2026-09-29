""" the parent graph's state: what the Coordinator, the workers, the Reviewer and the eligibility check share """

import operator
from typing import Annotated, TypedDict

from ..schemas.review import ReviewVerdict
from ..types.dossier import Dossier

from ..schemas.run_records import ModelCall, ToolInvocation


class WorkflowState(TypedDict):
    
    analyst_id: str
    incident: dict                   
    narrative: str | None       

    plans: Annotated[list[dict], operator.add]
    tasks: Annotated[dict[str, str], operator.or_]   
    
    dossier: Annotated[Dossier, operator.or_]

    reviews: Annotated[list[ReviewVerdict | None], operator.add]
    review_iterations: int

    analysis_run_id: str
    requires_review: bool      

    tool_invocations: Annotated[list[ToolInvocation], operator.add]
    model_calls: Annotated[list[ModelCall], operator.add]


