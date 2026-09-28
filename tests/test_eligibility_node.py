"""eligibility_check_node queues an escalated dossier with its snapshot."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.graph.nodes.eligibility import eligibility_check_node, review_snapshot
from fieldsight.harness.escalation.review import CitationReference
from fieldsight.repository import IncidentRepository, ReviewQueueRepository
from tests.test_analysis import normalized_fields


@pytest.fixture
def analyst_id():
    queue = ReviewQueueRepository()
    table = Table("analysts", MetaData(), autoload_with=queue.engine)
    with queue.engine.begin() as connection:
        analyst = connection.execute(
            insert(table).values(email=f"submitter-{uuid4()}@example.invalid", name="submitter").returning(table.c.analyst_id)
        ).scalar_one()
    yield analyst
    with queue.engine.begin() as connection:
        connection.execute(delete(queue.table).where(queue.table.c.submitting_analyst_id == analyst))
        connection.execute(delete(table).where(table.c.analyst_id == analyst))


def _state(analyst_id, incident_id, *, approved=True) -> dict:
    hit = {"doc_id": "osha-1904-7", "chunk_id": "osha-1904-7#3", "text": "..."}
    return {
        "analyst_id": str(analyst_id),
        "incident": {"incident_id": str(incident_id)},
        "dossier": {
            "recordability": {"task": "t", "proposal": {"chunk_ids": ["osha-1904-7#3"]}, "decisions": {}, "cited": {"osha-1904-7#3": hit}},
            "reportability": {"task": "t", "proposal": None, "decisions": {}, "cited": {}},
        },
        "reviews": [SimpleNamespace(approved=approved)],
        "review_iterations": 1,
    }


def test_review_snapshot_maps_cited_chunks_to_documents(analyst_id):
    snapshot = review_snapshot(_state(analyst_id, uuid4()))

    assert snapshot.submitting_analyst_id == analyst_id
    assert snapshot.citations == {"osha-1904-7#3": CitationReference(document_id="osha-1904-7", chunk_id="osha-1904-7#3")}


def test_escalated_dossier_is_queued_with_snapshot(analyst_id):
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    state = _state(analyst_id, incident_id)

    result = eligibility_check_node(state)

    assert result["requires_review"] is True
    queue = ReviewQueueRepository()
    [item] = [item for item in queue.list_pending() if item.incident_id == incident_id]
    pending = queue.get_pending(item.queue_id)
    assert pending is not None
    assert pending.submitting_analyst_id == analyst_id
    assert pending.original_payload == state["dossier"]
    assert set(pending.original_citations) == {"osha-1904-7#3"}


def test_missing_verdict_counts_as_not_approved(analyst_id):
    incident_id = IncidentRepository().create("Substation 7", normalized_fields())
    state = _state(analyst_id, incident_id)
    state["reviews"] = [None]

    result = eligibility_check_node(state)

    assert result["requires_review"] is True
