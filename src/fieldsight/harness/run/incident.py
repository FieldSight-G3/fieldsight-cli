""" the incident a turn is about, read cold from Postgres at the start of every command """

from uuid import UUID

from ...repository import IncidentRecord, IncidentRepository
from ...schemas.incidents import NormalizedIncident


def load_record(incident_id: object) -> IncidentRecord | None:
    """ the stored row, read once per turn; None when the id isn't a UUID or has no row, so check_turn routes to the analyst """

    try:
        key = UUID(str(incident_id).strip())
    except ValueError:
        return None
    return IncidentRepository().get(key)


def normalized(stored: IncidentRecord | None) -> NormalizedIncident | None:
    """ the stored row's normalized record """

    if stored is None:
        return None
    return NormalizedIncident.model_validate({**stored.normalized_fields, "incident_id": str(stored.incident_id)})


def photo_contradicts(stored: IncidentRecord | None) -> bool | None:
    """ whether any photo submit judged contradicts the narrative; None when no photo was judged, so it's unevaluated """

    verdicts = (stored.photo_verdicts or {}).get("items") if stored else None
    if not verdicts:
        return None
    return any(verdict["verdict"] == "contradicts" for verdict in verdicts)
