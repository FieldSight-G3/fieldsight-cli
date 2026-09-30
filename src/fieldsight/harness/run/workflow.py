""" the run_workflow route's contract: the Coordinator's graph, as run_turn calls it

    The budget is the turn meter's (harness/metering): it refuses the next model call once the session can't afford
    it. Stage 4 on the dossier runs inside the graph (its eligibility_check calls guard_dossier), so a blocked leg
    goes back to the Coordinator instead of ending the turn.
"""

from collections.abc import Callable

from ...schemas.incidents import NormalizedIncident
from ...types.run import WorkflowResult

# the Coordinator's graph: (incident, the ask question or None, correlation id) -> its result after eligibility_check
Workflow = Callable[[NormalizedIncident, str | None, str], WorkflowResult]
