from uuid import uuid4

import pytest

from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRepository,
    SessionRepository,
)


def test_incident_create_and_get_round_trip():
    repo = IncidentRepository()
    incident_id = repo.create(
        establishment="Substation 7",
        normalized_fields={"date_of_injury": "2026-02-01"},
        narrative="Test narrative",
    )

    record = repo.get(incident_id)

    assert record is not None
    assert record.incident_id == incident_id
    assert record.establishment == "Substation 7"
    assert record.normalized_fields == {"date_of_injury": "2026-02-01"}
    assert record.status == "submitted"


def test_incident_get_returns_none_for_missing_id():
    repo = IncidentRepository()
    assert repo.get(uuid4()) is None


def test_run_record_create_and_get_round_trip():
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", {"date_of_injury": "2026-02-01"})

    runs = RunRepository()
    correlation_id = uuid4()
    run_id = runs.create(
        correlation_id=correlation_id,
        command="analyze",
        incident_id=incident_id,
        rule_invocations={"R1": {"outcome": "recordable"}},
    )

    record = runs.get(run_id)

    assert record is not None
    assert record.correlation_id == correlation_id
    assert record.incident_id == incident_id
    assert record.command == "analyze"
    assert record.rule_invocations == {"R1": {"outcome": "recordable"}}


def test_review_queue_create_and_list_pending():
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", {"date_of_injury": "2026-02-01"})

    queue = ReviewQueueRepository()
    queue_id = queue.create(
        incident_id=incident_id,
        triggers={"confidence_floor": True},
    )

    record = queue.get(queue_id)
    pending = queue.list_pending()

    assert record is not None
    assert record.status == "pending"
    assert record.triggers == {"confidence_floor": True}
    assert any(r.queue_id == queue_id for r in pending)


def test_session_create_and_get_round_trip():
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", {"date_of_injury": "2026-02-01"})

    sessions = SessionRepository()
    analyst_id = uuid4()
    sessions.create(
        thread_id="test-thread-1",
        analyst_id=analyst_id,
        incident_id=incident_id,
        participant="coordinator",
    )

    record = sessions.get("test-thread-1")

    assert record is not None
    assert record.analyst_id == analyst_id
    assert record.incident_id == incident_id
    assert record.participant == "coordinator"

def test_session_get_or_create_reuses_the_row():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})
    sessions = SessionRepository()
    analyst_id = uuid4()

    first = sessions.get_or_create("reuse-thread", analyst_id, incident_id, "reviewer")
    second = sessions.get_or_create("reuse-thread", analyst_id, incident_id, "reviewer")

    assert first == second
    assert second.participant == "reviewer"


def test_session_get_or_create_refuses_a_thread_bound_elsewhere():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})
    sessions = SessionRepository()
    sessions.get_or_create("bound-thread", uuid4(), incident_id, "reviewer")

    with pytest.raises(ValueError):
        sessions.get_or_create("bound-thread", uuid4(), incident_id, "reviewer")