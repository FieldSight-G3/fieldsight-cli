"""Structured logs carry the correlation id from a contextvar; the API binds one per request."""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fieldsight.harness.escalation.review import submit_review
from fieldsight.interfaces.tool_api import CORRELATION_HEADER, create_app
from fieldsight.interfaces.tool_service import ToolResponse
from fieldsight.logging_context import (
    CorrelationFilter,
    JsonFormatter,
    correlated,
    correlation_id,
    with_correlation_id,
)


def _json_line(message: str) -> dict[str, Any]:
    record = logging.LogRecord("fieldsight.test", logging.INFO, __file__, 1, message, None, None)
    CorrelationFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_log_lines_carry_the_bound_correlation_id():
    with correlated("turn-42"):
        line = _json_line("tool invoked")
    assert line["correlation_id"] == "turn-42"
    assert line["message"] == "tool invoked"
    assert line["level"] == "INFO"
    assert _json_line("outside a turn")["correlation_id"] == "-"


def test_correlated_restores_the_outer_id_and_rejects_malformed_ids():
    with correlated("outer"):
        with correlated("inner"):
            assert correlation_id.get() == "inner"
        assert correlation_id.get() == "outer"
        with correlated("bad id\nwith newline") as fresh:
            assert fresh != "bad id\nwith newline" and len(fresh) == 36
    assert correlation_id.get() is None


def test_decorator_keeps_the_callers_id_or_binds_a_fresh_one():
    @with_correlation_id
    def current() -> str | None:
        """Report the bound id."""
        return correlation_id.get()

    assert current.__name__ == "current" and current.__doc__ == "Report the bound id."
    assert submit_review.__name__ == "submit_review"
    with correlated("caller"):
        assert current() == "caller"
    fresh = current()
    assert fresh is not None and fresh != "caller"
    assert correlation_id.get() is None


def test_concurrent_turns_keep_their_own_ids():
    def turn(name: str) -> str | None:
        with correlated(name):
            return _json_line("step")["correlation_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(turn, ["a", "b", "c", "d"])) == ["a", "b", "c", "d"]


class _Service:
    def get_incident_extraction(self, email: str, thread: str, payload: dict[str, Any]) -> ToolResponse:
        return ToolResponse(ok=True, result={"seen_correlation_id": correlation_id.get()})

    def find_similar_incidents(self, email: str, thread: str, payload: dict[str, Any]) -> ToolResponse:
        return ToolResponse(ok=True, result={})


def test_api_binds_echoes_and_releases_a_correlation_id_per_request():
    client = create_app(service=_Service(), caller_resolver=lambda: "analyst@example.invalid").test_client()  # type: ignore[arg-type]
    headers = {"X-Fieldsight-Thread-Id": "bound-thread", CORRELATION_HEADER: "turn-7"}

    response = client.post("/tools/get_incident_extraction", json={}, headers=headers)

    assert response.headers[CORRELATION_HEADER] == "turn-7"
    assert response.get_json()["result"] == {"seen_correlation_id": "turn-7"}
    generated = client.get("/health/live", headers={CORRELATION_HEADER: "not ok!"}).headers[CORRELATION_HEADER]
    assert generated != "not ok!" and len(generated) == 36
    assert correlation_id.get() is None
