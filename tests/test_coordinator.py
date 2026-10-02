"""The Coordinator's plan: a hazard_control dispatch stands only on a narrative quote, and a missing one costs that
worker, never the whole plan."""

import pytest
from pydantic import ValidationError

from fieldsight.graph.nodes import supervision
from fieldsight.schemas.agents import DispatchPlan

NARRATIVE = "He was racking a 12.47 kV breaker. The cubicle bus was energized at the time per the work order."


def plan(quote, *workers):
    return DispatchPlan.model_validate({"dispatches": [{"worker": w, "reason": "a fact"} for w in workers],
                                        "energized_equipment_quote": quote})


def coordinate(monkeypatch, dispatch_plan):
    monkeypatch.setattr(supervision, "_plan", lambda state: (dispatch_plan, []))
    return supervision.coordinator_node({"incident": {}, "narrative": NARRATIVE})["plans"][0]


def test_the_quote_is_required_in_the_schema_so_a_model_cant_leave_it_out():
    assert "energized_equipment_quote" in DispatchPlan.model_json_schema()["required"]
    with pytest.raises(ValidationError):
        DispatchPlan.model_validate({"dispatches": []})


def test_a_quote_differing_only_in_case_and_spacing_still_grounds_hazard_control(monkeypatch):
    decided = coordinate(monkeypatch, plan("the cubicle bus   was energized", "recordability", "hazard_control"))
    assert [d["worker"] for d in decided["dispatches"]] == ["recordability", "hazard_control"]


def test_hazard_control_without_a_quote_is_dropped_as_ungrounded_and_the_plan_stands(monkeypatch):
    decided = coordinate(monkeypatch, plan(None, "recordability", "hazard_control"))
    assert [d["worker"] for d in decided["dispatches"]] == ["recordability"]
    assert [d["worker"] for d in decided["ungrounded"]] == ["hazard_control"]


def test_a_quote_not_in_the_narrative_is_dropped(monkeypatch):
    decided = coordinate(monkeypatch, plan("the line was de-energized and grounded", "hazard_control"))
    assert decided["dispatches"] == [] and [d["worker"] for d in decided["ungrounded"]] == ["hazard_control"]


def test_a_worker_dispatched_twice_is_still_refused():
    with pytest.raises(ValidationError):
        plan(None, "recordability", "recordability")


def test_reportability_is_dropped_when_no_fact_could_make_the_event_reportable(monkeypatch):
    monkeypatch.setattr(supervision, "_plan", lambda state: (plan(None, "recordability", "reportability"), []))
    other = supervision.coordinator_node({"incident": {"event_type": "other", "death": False}, "narrative": NARRATIVE})
    admitted = supervision.coordinator_node({"incident": {"event_type": "inpatient_hospitalization", "death": False},
                                             "narrative": NARRATIVE})

    assert [d["worker"] for d in other["plans"][0]["dispatches"]] == ["recordability"]
    assert [d["worker"] for d in admitted["plans"][0]["dispatches"]] == ["recordability", "reportability"]
