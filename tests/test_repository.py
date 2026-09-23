from uuid import uuid4

from fieldsight.repository import (
    IncidentRepository,
    RunRecordRepository,
    ReviewQueueRepository,
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

    runs = RunRecordRepository()
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