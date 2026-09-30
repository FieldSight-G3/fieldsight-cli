"""The assembled turn: the graph's final state read back for the harness, with stage 4 applied, as the verified analyst."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.errors import ToolDenied
from fieldsight.harness.run.wiring import (
    graph_workflow,
    rag_answerer,
    turn,
    workflow_result,
)
from fieldsight.repository import (
    GatewayReadRepository,
    IncidentRepository,
    RunRecordRepository,
)
from fieldsight.schemas.incidents import NormalizedIncident


def normalized_fields() -> dict[str, Any]:
    """ a ready incident: every required field present and confident """
    return {
        "work_related": True, "new_case": True, "incident_at": datetime(2026, 9, 22, 8, tzinfo=UTC).isoformat(),
        "event_at": None, "learned_at": None, "event_type": "other", "admission_reason": None, "amputation_detail": None,
        "treatments": [], "death": False, "days_away": 1, "restricted_days": 0, "job_transfer": False,
        "loss_of_consciousness": False, "significant_diagnosis": False,
        "confidences": {"incident_at": 0.99, "days_away": 0.99},
    }


def no_answer(question: str, objections: list[str]):
    raise AssertionError("analyze never answers from retrieval")

AT = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
READY = NormalizedIncident(
    incident_id=str(uuid4()), work_related=True, new_case=True, incident_at=AT, event_at=None, learned_at=AT,
    event_type="other", admission_reason=None, amputation_detail=None, treatments=["sutures"], death=False,
    days_away=3, restricted_days=0, job_transfer=False, loss_of_consciousness=False, significant_diagnosis=False,
    confidences={"days_away": 0.95})
HIT = {"chunk_id": "CFR-1904-a", "doc_id": "CFR-1904", "score": 0.82, "text": "1904.7(b)(3)"}


def leg(column: str) -> dict:
    return {"task": "t", "decisions": {}, "cited": {"CFR-1904-a": HIT},
            "proposal": {"outcome": "recordable", "log_column": column, "day_count": 3, "missing_field": None,
                         "rationale": "Days away [1].", "chunk_ids": ["CFR-1904-a"]}}


def state(dossier: dict, reviews: list) -> dict:
    return {"dossier": dossier, "reviews": reviews, "review_iterations": len(reviews),
            "plans": [{"trigger": "initial", "dispatches": [{"worker": "recordability", "reason": "days away"}]},
                      {"trigger": "reviewer_rejected", "dispatches": [{"worker": "recordability", "reason": "wrong column"}]}]}


def test_the_final_state_reads_back_with_stage_4_applied():
    result = workflow_result(state({"recordability": leg("I")}, [SimpleNamespace(approved=False), {"approved": True}]), READY, "c-1")

    assert result.workers_dispatched == ["recordability"]
    assert result.reviewer_approved is True and result.reviewer_iterations == 2
    # the guard ran the rules itself and blocked the leg whose column no rule produced
    assert result.blocked == {"recordability": ["log_column must be H"]}
    assert result.rule_invocations and result.retrieval_scores == [0.82]
    assert any(event["failure"] == "unattributed_threshold" for event in result.events)


def test_no_reviews_and_no_hits_are_unevaluated_not_failed():
    result = workflow_result({"dossier": {}}, READY, "c-1")

    assert result.reviewer_approved is None and result.retrieval_scores is None
    assert result.blocked == {} and result.workers_dispatched == []


def test_the_workflow_runs_the_graph_on_the_stored_narrative():
    incident_id = IncidentRepository().create("Substation 7", normalized_fields(), narrative="Slipped on wet stairs.")
    incident = NormalizedIncident.model_validate({**normalized_fields(), "incident_id": str(incident_id)})
    analyst = uuid4()
    calls = []

    def fake_graph(analyst_id, incident, narrative):
        calls.append((analyst_id, incident.incident_id, narrative))
        return {"dossier": {}, "reviews": [SimpleNamespace(approved=True)], "review_iterations": 1}

    result = graph_workflow(analyst, run=fake_graph)(incident, None, "c-1")

    assert calls == [(analyst, str(incident_id), "Slipped on wet stairs.")]
    assert result.reviewer_approved is True


def test_objections_are_carried_into_the_regenerated_question():
    seen = []
    chain = SimpleNamespace(invoke=lambda inputs: seen.append(inputs["question"]) or "answer")
    answer = rag_answerer(chain)

    assert answer("What counts as first aid?", []) == "answer"
    answer("What counts as first aid?", ["uncited claim: 'sutures are first aid'"])

    assert seen[0] == "What counts as first aid?"
    assert "uncited claim: 'sutures are first aid'" in seen[1] and seen[1].startswith("What counts as first aid?")


@pytest.fixture
def granted():
    """ an analyst granted one establishment """
    repo = GatewayReadRepository()
    analysts = Table("analysts", MetaData(), autoload_with=repo.engine)
    establishment = f"Wiring {uuid4()}"
    with repo.engine.begin() as connection:
        analyst = connection.execute(
            insert(analysts).values(email=f"analyst-{uuid4()}@example.invalid", name="analyst").returning(analysts.c.analyst_id)
        ).scalar_one()
        connection.execute(insert(repo.grants).values(analyst_id=analyst, establishment=establishment))
    yield analyst, establishment
    with repo.engine.begin() as connection:
        connection.execute(delete(repo.grants).where(repo.grants.c.analyst_id == analyst))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst))


def test_a_turn_runs_end_to_end_as_the_verified_analyst(granted):
    analyst, establishment = granted
    incident_id = IncidentRepository().create(establishment, normalized_fields())

    def approved_graph(analyst_id, incident, narrative):
        return {"dossier": {}, "reviews": [SimpleNamespace(approved=True)], "review_iterations": 1,
                "plans": [{"trigger": "initial", "dispatches": [{"worker": "recordability", "reason": "days away"}]}]}

    run = turn({"command": "analyze", "incident_id": str(incident_id)}, analyst_id=analyst, run=approved_graph, answerer=no_answer)

    saved = RunRecordRepository().get(run.run_id)
    assert saved is not None and saved.incident_id == incident_id
    assert saved.workers_dispatched == {"items": ["recordability"]}


def test_a_turn_without_a_grant_is_denied_before_anything_is_read_or_written(granted):
    analyst, _ = granted
    incident_id = IncidentRepository().create(f"Elsewhere {uuid4()}", normalized_fields())

    def never(*_):
        raise AssertionError("the graph must not run for an unentitled analyst")

    with pytest.raises(ToolDenied) as denied:
        turn({"command": "analyze", "incident_id": str(incident_id)}, analyst_id=analyst, run=never, answerer=no_answer)

    assert denied.value.code == "not_entitled"
    runs = RunRecordRepository()
    with runs.engine.connect() as connection:
        assert connection.execute(runs.table.select().where(runs.table.c.incident_id == incident_id)).first() is None
