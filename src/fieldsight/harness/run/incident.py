""" the incident a turn is about, read cold from Postgres at the start of every command """

from uuid import UUID

from ...repository import IncidentRepository
from ...schemas.incidents import NormalizedIncident


def load_incident(incident_id: object) -> NormalizedIncident | None:
    """ the stored record, or None when the id isn't a UUID or has no row; check_turn then routes to the analyst """

    try:
        key = UUID(str(incident_id).strip())
    except ValueError:
        return None
    stored = IncidentRepository().get(key)
    if stored is None:
        return None
    return NormalizedIncident.model_validate({**stored.normalized_fields, "incident_id": str(stored.incident_id)})
