from uuid import UUID

import pytest

from fieldsight.checkpoint import (
    Participant,
    open_thread,
    thread_id,
)
from fieldsight.graph.specialists import WORKERS
from fieldsight.repository import IncidentRepository, SessionRepository

ANALYST = UUID("11111111-1111-1111-1111-111111111111")
OTHER_ANALYST = UUID("22222222-2222-2222-2222-222222222222")
INCIDENT = UUID("33333333-3333-3333-3333-333333333333")
OTHER_INCIDENT = UUID("44444444-4444-4444-4444-444444444444")


def test_thread_id_keeps_the_reviewer_format():
    assert thread_id(ANALYST, INCIDENT, Participant.REVIEWER) == f"{ANALYST}:{INCIDENT}:reviewer"


def test_thread_id_is_stable_across_input_types():
    assert thread_id(ANALYST, INCIDENT, "reviewer") == thread_id(str(ANALYST), str(INCIDENT), Participant.REVIEWER)


def test_every_participant_gets_its_own_thread():
    threads = {thread_id(ANALYST, INCIDENT, participant) for participant in Participant}
    assert len(threads) == len(Participant)


def test_analyst_and_incident_each_change_the_thread():
    base = thread_id(ANALYST, INCIDENT, Participant.RECORDABILITY)
    assert thread_id(OTHER_ANALYST, INCIDENT, Participant.RECORDABILITY) != base
    assert thread_id(ANALYST, OTHER_INCIDENT, Participant.RECORDABILITY) != base


def test_every_worker_is_a_participant():
    assert set(WORKERS) <= {participant.value for participant in Participant}


def test_unknown_participant_is_rejected():
    with pytest.raises(ValueError):
        thread_id(ANALYST, INCIDENT, "revewer")


@pytest.mark.parametrize("bad", ["", "a:b", "has space", "caf\u00e9"])
def test_bad_component_is_rejected(bad):
    with pytest.raises(ValueError):
        thread_id(bad, INCIDENT, Participant.COORDINATOR)

def test_open_thread_registers_once_and_returns_the_run_config():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})

    first = open_thread(ANALYST, incident_id, Participant.REVIEWER)
    second = open_thread(ANALYST, incident_id, "reviewer")

    assert first == second == {"configurable": {"thread_id": f"{ANALYST}:{incident_id}:reviewer"}}
    record = SessionRepository().get(first["configurable"]["thread_id"])
    assert (record.analyst_id, record.incident_id, record.participant) == (ANALYST, incident_id, "reviewer")


def test_open_thread_gives_each_participant_its_own_row():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})

    threads = [open_thread(ANALYST, incident_id, participant)["configurable"]["thread_id"] for participant in Participant]

    sessions = SessionRepository()
    assert [sessions.get(thread).participant for thread in threads] == [participant.value for participant in Participant]