"""Postgres integration tests for the ReviewStore adapter on ReviewQueueRepository."""

from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert, select
from sqlalchemy.exc import IntegrityError

from fieldsight.repository import IncidentRepository, ReviewQueueRepository
from fieldsight.review_decisions import CitationReference, ReviewDecision

DOSSIER = {"narrative": "Worker slipped on wet stairs.", "outcome": {"recordable": True}}
CITATIONS = {
    "c1": CitationReference(document_id="osha-1904-7", chunk_id="osha-1904-7#3"),
    "c2": CitationReference(document_id="osha-1904-39", chunk_id="osha-1904-39#1"),
}


@pytest.fixture
def analysts():
    """Seed a submitter and a reviewer; conftest does not truncate analysts."""
    queue = ReviewQueueRepository()
    table = Table("analysts", MetaData(), autoload_with=queue.engine)
    ids: list[UUID] = []
    with queue.engine.begin() as connection:
        for name in ("submitter", "reviewer"):
            ids.append(connection.execute(
                insert(table)
                .values(email=f"{name}-{uuid4()}@example.invalid", name=name)
                .returning(table.c.analyst_id)
            ).scalar_one())
    yield ids[0], ids[1]
    with queue.engine.begin() as connection:
        connection.execute(delete(queue.table).where(queue.table.c.submitting_analyst_id.in_(ids) | queue.table.c.reviewer_id.in_(ids)))
        connection.execute(delete(table).where(table.c.analyst_id.in_(ids)))


def _queue_review(submitter_id: UUID) -> tuple[UUID, UUID]:
    incidents = IncidentRepository()
    incident_id = incidents.create("Substation 7", {"date_of_injury": "2026-02-01"})
    incidents.save_analysis_for_review(
        incident_id=incident_id,
        correlation_id=uuid4(),
        outcome={"recordable": True},
        deciding_rule="R1",
        rule_invocations=[],
        escalation_triggers={"confidence_floor": True},
        submitting_analyst_id=submitter_id,
        dossier_snapshot=DOSSIER,
        citations=CITATIONS,
    )
    queue = ReviewQueueRepository()
    [pending] = [r for r in queue.list_pending() if r.incident_id == incident_id]
    return pending.queue_id, incident_id


def _decision(queue_id: UUID, incident_id: UUID, reviewer_id: UUID, *, action="approve", reason=None) -> ReviewDecision:
    return ReviewDecision(
        queue_id=queue_id,
        incident_id=incident_id,
        action=action,
        status="rejected" if action == "reject" else "approved",
        reviewer_id=reviewer_id,
        decided_at=datetime.now(UTC),
        original_payload=DOSSIER,
        edit=None,
        reason=reason,
    )


def _row(queue_id: UUID):
    queue = ReviewQueueRepository()
    with queue.engine.connect() as connection:
        return connection.execute(select(queue.table).where(queue.table.c.queue_id == queue_id)).mappings().one()


def test_get_pending_returns_snapshot_written_at_queue_time(analysts):
    submitter, _ = analysts
    queue_id, incident_id = _queue_review(submitter)

    pending = ReviewQueueRepository().get_pending(queue_id)

    assert pending is not None
    assert pending.queue_id == queue_id
    assert pending.incident_id == incident_id
    assert pending.submitting_analyst_id == submitter
    assert pending.original_payload == DOSSIER
    assert pending.original_citations == CITATIONS


def test_snapshot_is_independent_of_later_incident_outcome(analysts):
    submitter, _ = analysts
    queue_id, incident_id = _queue_review(submitter)
    IncidentRepository().save_analysis(incident_id, uuid4(), {"recordable": False}, "R5", [], {}, requires_review=False)

    pending = ReviewQueueRepository().get_pending(queue_id)

    assert pending is not None
    assert pending.original_payload == DOSSIER


def test_get_pending_returns_none_for_missing_queue_id():
    assert ReviewQueueRepository().get_pending(uuid4()) is None


def test_get_pending_returns_none_for_row_without_snapshot():
    incident_id = IncidentRepository().create("Substation 7", {"date_of_injury": "2026-02-01"})
    queue = ReviewQueueRepository()
    queue_id = queue.create(incident_id, {"confidence_floor": True})

    assert queue.get_pending(queue_id) is None


def test_record_if_pending_stores_decision_and_keeps_snapshot(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    decision = _decision(queue_id, incident_id, reviewer)

    assert ReviewQueueRepository().record_if_pending(decision) is True

    row = _row(queue_id)
    assert row["status"] == "approved"
    assert row["decision"] == decision.model_dump(mode="json")
    assert row["reviewer_id"] == reviewer
    assert row["decided_at"] == decision.decided_at
    assert row["dossier_snapshot"] == DOSSIER
    assert ReviewQueueRepository().get_pending(queue_id) is None


def test_second_decision_does_not_overwrite_first(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    queue = ReviewQueueRepository()
    first = _decision(queue_id, incident_id, reviewer)
    second = _decision(queue_id, incident_id, reviewer, action="reject", reason="Changed my mind")

    assert queue.record_if_pending(first) is True
    assert queue.record_if_pending(second) is False

    row = _row(queue_id)
    assert row["status"] == "approved"
    assert row["decision"] == first.model_dump(mode="json")


def test_record_if_pending_rejects_mismatched_incident(analysts):
    submitter, reviewer = analysts
    queue_id, _ = _queue_review(submitter)
    other_incident = IncidentRepository().create("Substation 9", {"date_of_injury": "2026-02-02"})

    assert ReviewQueueRepository().record_if_pending(_decision(queue_id, other_incident, reviewer)) is False
    assert _row(queue_id)["status"] == "pending"


def test_concurrent_decisions_only_one_wins(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    barrier = Barrier(2)
    results: list[bool] = []

    def decide(action: str, reason: str | None) -> None:
        queue = ReviewQueueRepository()
        decision = _decision(queue_id, incident_id, reviewer, action=action, reason=reason)
        barrier.wait()
        results.append(queue.record_if_pending(decision))

    threads = [Thread(target=decide, args=("approve", None)), Thread(target=decide, args=("reject", "No"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == [False, True]


def test_database_refuses_self_review(analysts):
    submitter, _ = analysts
    queue_id, incident_id = _queue_review(submitter)

    with pytest.raises(IntegrityError):
        ReviewQueueRepository().record_if_pending(_decision(queue_id, incident_id, submitter))
    assert _row(queue_id)["status"] == "pending"


def test_save_analysis_for_review_rolls_back_for_missing_incident(analysts):
    submitter, _ = analysts
    missing = uuid4()

    with pytest.raises(LookupError):
        IncidentRepository().save_analysis_for_review(
            incident_id=missing,
            correlation_id=uuid4(),
            outcome={},
            deciding_rule="R1",
            rule_invocations=[],
            escalation_triggers={},
            submitting_analyst_id=submitter,
            dossier_snapshot=DOSSIER,
            citations=CITATIONS,
        )
    queue = ReviewQueueRepository()
    with queue.engine.connect() as connection:
        assert connection.execute(select(queue.table).where(queue.table.c.incident_id == missing)).first() is None
