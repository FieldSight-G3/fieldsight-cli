""" the LangGraph checkpointer: one thread per (analyst, incident, participant), so no participant's state merges with another's """

from enum import StrEnum
from uuid import UUID

from fieldsight.repository import SessionRepository


class Participant(StrEnum):
    """ every graph participant that keeps its own checkpointer thread (sections 5 and 10) """

    COORDINATOR = "coordinator"
    RECORDABILITY = "recordability"
    REPORTABILITY = "reportability"
    HAZARD_CONTROL = "hazard_control"
    REVIEWER = "reviewer"


def thread_id(analyst_id: UUID | str, incident_id: UUID | str, participant: Participant | str) -> str:
    """ the stable thread for one participant on one incident for one analyst, so a later turn resumes it """

    # an unknown participant is a ValueError, never a stray thread
    role = Participant(participant)
    parts = (str(analyst_id), str(incident_id))
    for part in parts:
        # ':' separates the parts; the Gateway's thread header also refuses whitespace and non-ASCII
        if not part or ":" in part or not part.isascii() or any(char.isspace() for char in part):
            raise ValueError(f"invalid thread id component: {part!r}")
    return f"{parts[0]}:{parts[1]}:{role}"

def open_thread(
    analyst_id: UUID, incident_id: UUID, participant: Participant | str, sessions: SessionRepository | None = None
) -> dict:
    """ the run config for one participant's thread, registered in sessions the first time and reused after """

    role = Participant(participant)
    thread = thread_id(analyst_id, incident_id, role)
    (sessions or SessionRepository()).get_or_create(thread, analyst_id, incident_id, role.value)
    return {"configurable": {"thread_id": thread}}

