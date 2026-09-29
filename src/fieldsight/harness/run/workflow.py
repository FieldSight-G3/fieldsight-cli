""" the run_workflow route: the bounds check, then the Coordinator's graph

    stage 4 on the dossier runs inside the graph (its eligibility_check calls guard_dossier), so a blocked leg
    goes back to the Coordinator instead of ending the turn
"""

from collections.abc import Callable

from ...schemas.incidents import NormalizedIncident
from ...types.run import WorkflowResult
from ..bounds import BoundsConfig, LegRequest, SessionUsage, preflight, record_usage
from ..guardrails.common import refuse

# the Coordinator's graph: (incident, the ask question or None, correlation id) -> its result after eligibility_check
Workflow = Callable[[NormalizedIncident, str | None, str], WorkflowResult]


def run_workflow(workflow: Workflow, incident: NormalizedIncident, question: str | None, *, usage: SessionUsage,
                 limits: BoundsConfig, correlation_id: str) -> dict:
    """ returns the refusal when the session's budget is spent, otherwise the graph's result; and the usage either way """

    stop = preflight(usage, limits, LegRequest(kind="graph"))
    if not stop.allowed:
        return {"result": None, "usage": usage,
                "refusal": refuse("bound_reached", f"This session's {stop.reason_code} limit ({stop.limit}) is spent.")}
    result = workflow(incident, question, correlation_id)
    return {"result": result, "usage": record_usage(usage, result.usage), "refusal": None}
