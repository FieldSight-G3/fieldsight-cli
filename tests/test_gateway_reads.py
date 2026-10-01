"""The turn reads both Gateway tools as the analyst at turn start; the workers' tools serve what came back."""

from uuid import UUID, uuid4

import pytest
from botocore.exceptions import ClientError

from fieldsight.aws.gateway_reads import GATEWAY_UNAVAILABLE, GatewayReads, _response
from fieldsight.ingest import embedding
from fieldsight.services.agent_runtime import handle
from fieldsight.tools.tools import find_similar_incidents, get_incident_extraction

INCIDENT = {"incident_id": "6fc5494f-b41d-5bc1-ace8-da2d0119781f", "days_away": 1}
PRECEDENT = {"incident_id": "60f2ee61-8c21-5e24-a7ed-65711dbc9a25", "outcome": {"recordable": False},
             "deciding_rule": "R1", "similarity_score": 0.8, "matching_narrative_span": "a cut"}


def reads(**kwargs) -> dict:
    return GatewayReads(**kwargs).model_dump(mode="json")


class TestResponse:
    def test_a_text_block_tool_response_is_parsed(self):
        assert _response([{"type": "text", "text": '{"ok": true, "result": {"items": []}}'}])["ok"] is True

    def test_a_gateway_error_prefix_before_the_body_is_skipped(self):
        response = _response('HTTP 422: {"ok": false, "error": {"code": "insufficient_data", "message": "no embedding"}}')
        assert response["error"]["message"] == "no embedding"

    def test_text_with_no_tool_response_is_an_error(self):
        with pytest.raises(ValueError):
            _response("upstream timed out")


class TestWorkerTools:
    def test_without_a_gateway_the_extraction_is_the_harness_copy(self):
        assert get_incident_extraction.func({"incident": INCIDENT, "gateway": None}) == {"fields": {"days_away": 1}}

    def test_with_a_gateway_the_extraction_is_what_the_gateway_returned(self):
        state = {"incident": INCIDENT, "gateway": reads(extraction={"incident_id": INCIDENT["incident_id"],
                                                                     "normalized_fields": {"days_away": 2}})}
        assert get_incident_extraction.func(state) == {"fields": {"days_away": 2}}

    def test_a_failed_gateway_read_is_named_never_replaced_by_the_local_copy(self):
        state = {"incident": INCIDENT, "gateway": reads(unavailable={"get_incident_extraction": GATEWAY_UNAVAILABLE})}
        assert get_incident_extraction.func(state) == {"unavailable": GATEWAY_UNAVAILABLE}

    def test_similar_incidents_come_only_from_the_gateway(self):
        assert find_similar_incidents.func({"gateway": reads(similar=[PRECEDENT])}) == {"items": [PRECEDENT]}
        assert "unavailable" in find_similar_incidents.func({"gateway": None})
        missing = reads(unavailable={"find_similar_incidents": "The bound incident has no narrative embedding"})
        assert find_similar_incidents.func({"gateway": missing}) == {"unavailable": "The bound incident has no narrative embedding"}


class TestRuntime:
    def run(self, read_gateway, payload=None):
        seen: dict = {}

        def run(request, **kwargs):
            seen.update(kwargs)

            class Result:
                def model_dump(self, mode):
                    return {}

            return Result()

        analyst = uuid4()
        payload = payload or {"command": "analyze", "incident_id": INCIDENT["incident_id"], "caller_proof": "proof"}
        outcome = handle(payload, "session-" + "x" * 30, resolve_analyst=lambda proof, session: analyst, run=run,
                         read_gateway=read_gateway)
        return outcome, seen, analyst

    def test_the_reads_use_the_invokers_proof_and_session_then_reach_the_turn(self):
        calls = []
        gateway = GatewayReads(similar=[])

        def read(analyst, incident, session, proof):
            calls.append((analyst, incident, session, proof))
            return gateway

        outcome, seen, analyst = self.run(read)
        assert outcome["ok"] and seen["gateway"] is gateway
        assert calls == [(analyst, UUID(INCIDENT["incident_id"]), "session-" + "x" * 30, "proof")]

    def test_no_incident_means_no_reads(self):
        def read(*args):
            raise AssertionError("no incident to read")

        outcome, seen, _ = self.run(read, {"command": "ask", "question": "what is first aid?", "caller_proof": "proof"})
        assert outcome["ok"] and "gateway" not in seen


class TestEmbedding:
    def test_no_narrative_has_no_embedding(self):
        assert embedding.embed_narrative(None) is None

    def test_a_bedrock_failure_stores_no_embedding_instead_of_failing_the_write(self, monkeypatch):
        class Down:
            def embed_query(self, text):
                raise ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "InvokeModel")

        monkeypatch.setattr(embedding.clients, "embeddings", Down)
        assert embedding.embed_narrative("a cut on the hand") is None
