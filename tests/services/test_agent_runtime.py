"""The AgentCore Runtime entrypoint: the caller proof names the analyst, and every denial is a structured result."""

from uuid import UUID, uuid4

import pytest

from fieldsight.errors import ToolDenied
from fieldsight.services import agent_runtime
from fieldsight.services.agent_runtime import handle
from fieldsight.types.run import TurnRun

SESSION = "runtime-session-0123456789abcdef0123456789"
ANALYST = UUID(int=42)


def ok_resolver(proof: str, session_id: str) -> UUID:
    assert proof == "signed-proof" and session_id == SESSION
    return ANALYST


def recording_turn(calls: list):
    def run(request: dict, *, analyst_id: UUID) -> TurnRun:
        calls.append((request, analyst_id))
        return TurnRun(run_id=uuid4(), correlation_id=uuid4(), command=request.get("command", "invalid"), route=None)
    return run


def test_a_verified_turn_runs_without_the_proof_in_the_request():
    calls: list = []
    payload = {"command": "analyze", "incident_id": "inc-1", "caller_proof": "signed-proof"}

    response = handle(payload, SESSION, resolve_analyst=ok_resolver, run=recording_turn(calls))

    assert response["ok"] is True and response["error"] is None
    assert response["result"]["command"] == "analyze"
    assert calls == [({"command": "analyze", "incident_id": "inc-1"}, ANALYST)]
    assert "signed-proof" not in str(response)


@pytest.mark.parametrize(("payload", "session", "code"), [
    (["not", "an", "object"], SESSION, "invalid_input"),
    ({"command": "analyze"}, None, "unauthenticated"),
])
def test_malformed_requests_are_refused(payload, session, code):
    calls: list = []
    response = handle(payload, session, resolve_analyst=ok_resolver, run=recording_turn(calls))

    assert response == {"ok": False, "result": None, "error": {"code": code, "message": response["error"]["message"]}}
    assert calls == []


def test_a_denial_from_the_resolver_or_the_turn_is_structured():
    def bad_proof(proof: str, session_id: str) -> UUID:
        raise ToolDenied("unauthenticated", "Valid enrolled IAM role proof is required")

    def no_grant(request: dict, *, analyst_id: UUID) -> TurnRun:
        raise ToolDenied("not_entitled", "Caller has no grant for this establishment")

    assert handle({}, SESSION, resolve_analyst=bad_proof, run=recording_turn([]))["error"]["code"] == "unauthenticated"
    assert handle({"caller_proof": "signed-proof"}, SESSION, resolve_analyst=ok_resolver, run=no_grant)["error"]["code"] == "not_entitled"


def test_the_agentcore_app_serves_invocations_and_ping():
    pytest.importorskip("bedrock_agentcore", reason="the AgentCore SDK is installed only in the Runtime image")
    from starlette.testclient import TestClient

    calls: list = []
    client = TestClient(agent_runtime.build_app(ok_resolver, recording_turn(calls)))

    assert client.get("/ping").status_code == 200
    response = client.post("/invocations", json={"command": "analyze", "incident_id": "inc-1", "caller_proof": "signed-proof"},
                           headers={"X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": SESSION})

    assert response.status_code == 200 and response.json()["ok"] is True
    assert calls == [({"command": "analyze", "incident_id": "inc-1"}, ANALYST)]
