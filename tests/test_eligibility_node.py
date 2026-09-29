"""The eligibility node writes nothing; ReviewSnapshot.of builds the queue snapshot the harness saves."""

from types import SimpleNamespace
from uuid import uuid4

from fieldsight.graph.nodes.eligibility import eligibility_check_node
from fieldsight.harness.analysis import ReviewSnapshot
from fieldsight.harness.escalation.review import CitationReference
from fieldsight.repository import (
    IncidentRepository,
    ReviewQueueRepository,
    RunRecordRepository,
)
from tests.test_analysis import normalized_fields

HIT = {"doc_id": "CFR-1904", "chunk_id": "CFR-1904-0123456789ab", "text": "1904.39(a)(2)"}
DOSSIER = {
    "reportability": {"task": "t", "proposal": {"chunk_ids": [HIT["chunk_id"]]}, "decisions": {}, "cited": {HIT["chunk_id"]: HIT}},
    "recordability": {"task": "t", "proposal": None, "decisions": {}, "cited": {}},
}


def test_the_node_hands_back_without_writing():
    fields = normalized_fields()
    fields["confidences"]["incident_at"] = 0.59
    incident_id = IncidentRepository().create("Substation 7", fields)
    runs = RunRecordRepository()
    state = {"analyst_id": str(uuid4()), "incident": {"incident_id": str(incident_id)}, "dossier": DOSSIER,
             "reviews": [SimpleNamespace(approved=True)], "review_iterations": 1}

    assert eligibility_check_node(state) == {}

    assert not any(item.incident_id == incident_id for item in ReviewQueueRepository().list_pending())
    with runs.engine.connect() as connection:
        written = connection.execute(runs.table.select().where(runs.table.c.incident_id == incident_id)).first()
    assert written is None


def test_snapshot_maps_every_cited_chunk_to_its_document():
    analyst = uuid4()

    snapshot = ReviewSnapshot.of(str(analyst), DOSSIER)

    assert snapshot.submitting_analyst_id == analyst
    assert snapshot.dossier == DOSSIER
    assert snapshot.citations == {HIT["chunk_id"]: CitationReference(document_id="CFR-1904", chunk_id=HIT["chunk_id"])}


def test_a_case_routed_straight_to_a_human_still_has_a_snapshot():
    snapshot = ReviewSnapshot.of(uuid4(), None)

    assert snapshot.dossier == {} and snapshot.citations == {}
