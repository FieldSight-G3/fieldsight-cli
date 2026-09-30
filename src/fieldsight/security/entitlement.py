""" entitlement for in-process reads, checked on every call: the analyst must hold a grant over the incident's establishment

    The Gateway read tools (tool_store) call this too, so both paths judge access alike.
    Tools return the denial as a structured result; the harness can raise it instead.
"""

from typing import Any
from uuid import UUID

from ..errors import ToolDenied
from ..interfaces.tool_service import ToolFailure, ToolResponse
from ..repository import GatewayReadRepository


def require_grant(analyst_id: UUID | str, incident_id: UUID | str, *, repository: GatewayReadRepository | None = None) -> dict[str, Any]:
    """ raise ToolDenied unless the analyst holds a grant over the incident's establishment; returns the incident row """

    try:
        analyst, incident = UUID(str(analyst_id)), UUID(str(incident_id))
    except ValueError:
        raise ToolDenied("unauthenticated", "A verified analyst and a bound incident are required") from None
    repository = repository or GatewayReadRepository()
    row = repository.tool_incident(incident)
    if row is None:
        raise ToolDenied("not_found", "The bound incident is unavailable")
    if not repository.has_grant(analyst, row["establishment"]):
        raise ToolDenied("not_entitled", "Caller has no grant for this establishment")
    return row


def entitlement_denial(state: dict[str, Any], *, repository: GatewayReadRepository | None = None) -> dict[str, Any] | None:
    """ for a native tool: None when the state's analyst may read its incident, otherwise the structured denial to return

        The analyst and incident come from the dispatcher's state, never from a model-filled argument.
    """

    incident = state.get("incident") or {}
    try:
        require_grant(state.get("analyst_id", ""), incident.get("incident_id", ""), repository=repository)
    except ToolDenied as denied:
        return ToolResponse(ok=False, error=ToolFailure(code=denied.code, message=str(denied))).model_dump(mode="json")
    return None
