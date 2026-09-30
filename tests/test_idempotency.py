"""Idempotency keys come from (session_id, tool_name, canonicalized arguments), order-independent."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from fieldsight.harness.idempotency import canonicalize, idempotency_key
from fieldsight.schemas.tools import SimilarIncidentsInput

SESSION = "analyst-1:inc-4:hazard_control"


def test_key_order_does_not_change_the_key():
    a = {"limit": 3, "filters": {"doc_type": "regulation", "section_path": "1904.39"}}
    b = {"filters": {"section_path": "1904.39", "doc_type": "regulation"}, "limit": 3}
    assert canonicalize(a) == canonicalize(b)
    assert idempotency_key(SESSION, "find_similar_incidents", a) == idempotency_key(SESSION, "find_similar_incidents", b)


def test_session_tool_and_values_each_change_the_key():
    base = idempotency_key(SESSION, "find_similar_incidents", {"limit": 3})
    assert idempotency_key("analyst-1:inc-5:hazard_control", "find_similar_incidents", {"limit": 3}) != base
    assert idempotency_key(SESSION, "get_incident_extraction", {"limit": 3}) != base
    assert idempotency_key(SESSION, "find_similar_incidents", {"limit": 4}) != base


def test_list_order_is_meaningful_but_set_order_is_not():
    assert canonicalize({"ids": [1, 2]}) != canonicalize({"ids": [2, 1]})
    assert canonicalize({"ids": {"b", "a"}}) == canonicalize({"ids": {"a", "b"}})


def test_equal_values_of_different_types_share_a_key():
    assert canonicalize({"limit": 2}) == canonicalize({"limit": 2.0}) == canonicalize({"limit": Decimal(2)})
    assert canonicalize({"id": UUID(int=1)}) == canonicalize({"id": str(UUID(int=1))})
    at = datetime(2026, 9, 28, 12, tzinfo=UTC)
    assert canonicalize({"at": at}) == canonicalize({"at": at.isoformat()})


def test_pydantic_arguments_match_their_plain_form():
    assert canonicalize({"args": SimilarIncidentsInput(limit=3)}) == canonicalize({"args": {"limit": 3}})
    assert idempotency_key(SESSION, "find_similar_incidents", SimilarIncidentsInput(limit=3)) == (
        idempotency_key(SESSION, "find_similar_incidents", {"limit": 3})
    )


def test_the_key_is_a_uuid_stable_across_runs():
    key = idempotency_key(SESSION, "find_similar_incidents", {"limit": 3})
    assert isinstance(key, UUID)
    assert key == idempotency_key(SESSION, "find_similar_incidents", {"limit": 3})


def test_parts_cannot_run_together():
    # "a" + "b:c" and "a:b" + "c" must not collide once joined
    assert idempotency_key("a", "b:c", {}) != idempotency_key("a:b", "c", {})


@pytest.mark.parametrize("arguments", [{"x": float("nan")}, {"x": float("inf")}, {1: "non-string key"}, {"x": object()}])
def test_uncanonicalizable_arguments_are_refused(arguments):
    with pytest.raises((TypeError, ValueError)):
        canonicalize(arguments)


@pytest.mark.parametrize(("session", "tool"), [(" ", "find_similar_incidents"), (SESSION, "")])
def test_session_and_tool_are_required(session, tool):
    with pytest.raises(ValueError):
        idempotency_key(session, tool, {})
