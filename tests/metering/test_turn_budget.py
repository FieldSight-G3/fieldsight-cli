"""A turn's model spend lands in its session usage, and a turn stopped by the ceiling still leaves a run record."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from sqlalchemy import MetaData, Table, delete, insert

from fieldsight.harness.bounds import BoundsConfig
from fieldsight.harness.run.wiring import turn
from fieldsight.repository import (
    GatewayReadRepository,
    IncidentRepository,
    RunRecordRepository,
)


def normalized_fields() -> dict[str, Any]:
    return {
        "work_related": True, "new_case": True, "incident_at": datetime(2026, 9, 22, 8, tzinfo=UTC).isoformat(),
        "event_at": None, "learned_at": None, "event_type": "other", "admission_reason": None, "amputation_detail": None,
        "treatments": [], "death": False, "days_away": 1, "restricted_days": 0, "job_transfer": False,
        "loss_of_consciousness": False, "significant_diagnosis": False,
        "confidences": {"incident_at": 0.99, "days_away": 0.99},
    }


def no_answer(question: str, objections: list[str]):
    raise AssertionError("analyze never answers from retrieval")


class FakeBedrock:
    def __init__(self) -> None:
        self.calls = 0

    def converse(self, **kwargs):
        self.calls += 1
        return {"output": {"message": {"role": "assistant", "content": [{"text": "plan"}]}},
                "usage": {"inputTokens": 6000, "outputTokens": 800, "totalTokens": 6800},
                "stopReason": "end_turn", "metrics": {"latencyMs": 5}, "ResponseMetadata": {}}


def graph_calling_the_model(bedrock: FakeBedrock, calls: int):
    """ a stand-in graph that makes real (faked-client) model calls, then finishes approved """

    def run(analyst_id, incident, narrative):
        chat = ChatBedrockConverse(model_id="deepseek.v3.2", region_name="us-east-1", max_tokens=900)
        chat.client = bedrock
        for _ in range(calls):
            chat.invoke([HumanMessage("plan the dispatch")])
        return {"dossier": {}, "reviews": [SimpleNamespace(approved=True)], "review_iterations": 1}

    return run


@pytest.fixture
def granted():
    repo = GatewayReadRepository()
    analysts = Table("analysts", MetaData(), autoload_with=repo.engine)
    establishment = f"Metering {uuid4()}"
    with repo.engine.begin() as connection:
        analyst = connection.execute(
            insert(analysts).values(email=f"analyst-{uuid4()}@example.invalid", name="analyst").returning(analysts.c.analyst_id)
        ).scalar_one()
        connection.execute(insert(repo.grants).values(analyst_id=analyst, establishment=establishment))
    yield analyst, IncidentRepository().create(establishment, normalized_fields())
    with repo.engine.begin() as connection:
        connection.execute(delete(repo.grants).where(repo.grants.c.analyst_id == analyst))
        connection.execute(delete(analysts).where(analysts.c.analyst_id == analyst))


def test_the_turns_model_spend_is_carried_in_its_session_usage(granted):
    analyst, incident_id = granted
    bedrock = FakeBedrock()

    run = turn({"command": "analyze", "incident_id": str(incident_id)}, analyst_id=analyst,
               run=graph_calling_the_model(bedrock, calls=2), answerer=no_answer, limits=BoundsConfig())

    assert bedrock.calls == 2
    assert run.usage is not None and run.usage.cost_usd == Decimal("0.01040")
    assert run.refusal is None


def test_a_turn_stopped_by_the_ceiling_is_recorded_and_names_it(granted):
    analyst, incident_id = granted
    bedrock = FakeBedrock()
    # the first call fits; the second one's worst case would pass the ceiling
    limits = BoundsConfig(session_cost_ceiling_usd=Decimal("0.006"))

    run = turn({"command": "analyze", "incident_id": str(incident_id)}, analyst_id=analyst,
               run=graph_calling_the_model(bedrock, calls=3), answerer=no_answer, limits=limits)

    assert bedrock.calls == 1
    assert run.refusal is not None and run.refusal["reason"] == "bound_reached"
    assert "session_cost_usd" in run.refusal["message"]
    assert run.usage is not None and run.usage.cost_usd == Decimal("0.00520")
    assert RunRecordRepository().get(run.run_id) is not None
