"""Postgres integration tests for the ReviewStore adapter on ReviewQueueRepository."""

from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Barrier, Thread
from uuid import UUID, uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert, select
from sqlalchemy.exc import IntegrityError, OperationalError

from fieldsight.harness.bounds import BoundsConfig
from fieldsight.harness.escalation.review import (
    CitationReference,
    ReviewConflict,
    ReviewDecision,
    ReviewWriteFailed,
)
from fieldsight.harness.escalation.snapshot import ReviewSnapshot
from fieldsight.repository import IncidentRepository, ReviewQueueRepository

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


def _queue_review(submitter_id: UUID, incident_id: UUID | None = None) -> tuple[UUID, UUID]:
    incidents = IncidentRepository()
    incident_id = incident_id or incidents.create("Substation 7", {"date_of_injury": "2026-02-01"})
    incidents.save_analysis(
        incident_id=incident_id,
        correlation_id=uuid4(),
        outcome={"recordable": True},
        deciding_rule="R1",
        rule_invocations=[],
        escalation_triggers={"confidence_floor": True},
        review=ReviewSnapshot(submitting_analyst_id=submitter_id, dossier=DOSSIER, citations=CITATIONS),
    )
    queue = ReviewQueueRepository()
    [pending] = [r for r in queue.list_pending() if r.incident_id == incident_id]
    return pending.queue_id, incident_id


def _incident(incident_id: UUID) -> tuple[str, UUID | None]:
    """ the incident's status and the key of the write after approval that closed it, if any """
    incidents = IncidentRepository()
    statement = select(incidents.table.c.status, incidents.table.c.execution_key).where(incidents.table.c.incident_id == incident_id)
    with incidents.engine.connect() as connection:
        return tuple(connection.execute(statement).one())


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
    IncidentRepository().save_analysis(incident_id, uuid4(), {"recordable": False}, "R5", [], {})

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


def test_save_analysis_with_review_rolls_back_for_missing_incident(analysts):
    submitter, _ = analysts
    missing = uuid4()

    with pytest.raises(LookupError):
        IncidentRepository().save_analysis(
            incident_id=missing,
            correlation_id=uuid4(),
            outcome={},
            deciding_rule="R1",
            rule_invocations=[],
            escalation_triggers={},
            review=ReviewSnapshot(submitting_analyst_id=submitter, dossier=DOSSIER, citations=CITATIONS),
        )
    queue = ReviewQueueRepository()
    with queue.engine.connect() as connection:
        assert connection.execute(select(queue.table).where(queue.table.c.incident_id == missing)).first() is None


def test_reviewer_entitled_needs_a_grant_on_the_incident_establishment(analysts):
    submitter, reviewer = analysts
    establishment = f"Entitlement test {uuid4()}"
    incident_id = IncidentRepository().create(establishment, {"date_of_injury": "2026-02-01"})
    queue = ReviewQueueRepository()
    grants = Table("grants", MetaData(), autoload_with=queue.engine)
    with queue.engine.begin() as connection:
        connection.execute(insert(grants).values(analyst_id=reviewer, establishment=establishment))
    try:
        assert queue.reviewer_entitled(reviewer, incident_id) is True
        assert queue.reviewer_entitled(submitter, incident_id) is False
        assert queue.reviewer_entitled(reviewer, uuid4()) is False
    finally:
        with queue.engine.begin() as connection:
            connection.execute(delete(grants).where(grants.c.analyst_id == reviewer))


class FlakyEngine:
    """Wraps a real engine; each begin() can fail before the transaction or drop after it commits."""

    def __init__(self, engine, failures: list[str]) -> None:
        self.engine = engine
        self.failures = list(failures)

    @contextmanager
    def begin(self):
        failure = self.failures.pop(0) if self.failures else None
        if failure == "before":
            raise OperationalError("BEGIN", {}, Exception("connection refused"))
        with self.engine.begin() as connection:
            yield connection
        if failure == "after_commit":
            raise OperationalError("COMMIT", {}, Exception("connection dropped"))


NO_WAIT = BoundsConfig(db_write_max_attempts=3, db_write_backoff_seconds=0)


def test_record_if_pending_retries_a_transient_failure(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    queue = ReviewQueueRepository()
    queue.engine = FlakyEngine(queue.engine, ["before"])

    assert queue.record_if_pending(_decision(queue_id, incident_id, reviewer), limits=NO_WAIT) is True
    assert _row(queue_id)["status"] == "approved"


def test_commit_hidden_by_a_dropped_connection_is_not_a_conflict(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    queue = ReviewQueueRepository()
    queue.engine = FlakyEngine(queue.engine, ["after_commit"])
    decision = _decision(queue_id, incident_id, reviewer)

    assert queue.record_if_pending(decision, limits=NO_WAIT) is True
    assert _row(queue_id)["decision"] == decision.model_dump(mode="json")


def test_retry_after_another_decision_landed_is_a_conflict(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    first = _decision(queue_id, incident_id, reviewer)
    ReviewQueueRepository().record_if_pending(first)
    queue = ReviewQueueRepository()
    queue.engine = FlakyEngine(queue.engine, ["before"])

    assert queue.record_if_pending(_decision(queue_id, incident_id, reviewer, action="reject", reason="Late"), limits=NO_WAIT) is False
    assert _row(queue_id)["decision"] == first.model_dump(mode="json")


def test_an_approval_closes_the_incident_once_per_key(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    queue = ReviewQueueRepository()
    # the first attempt commits, then the connection drops; the retry with the same key applies nothing twice
    queue.engine = FlakyEngine(queue.engine, ["after_commit"])
    key = uuid4()

    assert queue.record_if_pending(_decision(queue_id, incident_id, reviewer), execution_key=key, limits=NO_WAIT) is True
    assert _incident(incident_id) == ("closed", key)


def test_a_second_approval_under_another_key_is_refused(analysts):
    submitter, reviewer = analysts
    first_queue, incident_id = _queue_review(submitter)
    first_key = uuid4()
    ReviewQueueRepository().record_if_pending(_decision(first_queue, incident_id, reviewer), execution_key=first_key)
    second_queue, _ = _queue_review(submitter, incident_id)

    with pytest.raises(ReviewConflict):
        ReviewQueueRepository().record_if_pending(_decision(second_queue, incident_id, reviewer), execution_key=uuid4())
    assert _incident(incident_id) == ("closed", first_key)
    assert _row(second_queue)["status"] == "pending"


def test_exhausted_retries_fail_clearly_and_leave_the_row_pending(analysts):
    submitter, reviewer = analysts
    queue_id, incident_id = _queue_review(submitter)
    queue = ReviewQueueRepository()
    queue.engine = FlakyEngine(queue.engine, ["before"] * 3)

    with pytest.raises(ReviewWriteFailed):
        queue.record_if_pending(_decision(queue_id, incident_id, reviewer), limits=NO_WAIT)
    assert _row(queue_id)["status"] == "pending"
