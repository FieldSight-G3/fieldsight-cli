"""Exercise the HTTP boundary with a test-only verified identity resolver."""

from __future__ import annotations

import unittest
from typing import Any

from flask import request

from fieldsight.errors import ToolDenied
from fieldsight.interfaces.tool_api import create_app
from fieldsight.schemas.incidents import SimilarCandidate
from fieldsight.tools.service import ToolService


class FakeStore:
    def extraction(self, verified_email: str, thread_id: str) -> dict[str, Any]:
        if (verified_email, thread_id) != ("logan@example.invalid", "bound-thread"):
            raise ToolDenied("not_entitled", "No session is bound to this caller")
        return {"normalized_fields": {"days_away": 2}}

    def similar(self, verified_email: str, thread_id: str, limit: int) -> list[SimilarCandidate]:
        if (verified_email, thread_id) != ("logan@example.invalid", "bound-thread"):
            raise ToolDenied("not_entitled", "No session is bound to this caller")
        return []


class ToolApiTests(unittest.TestCase):
    def setUp(self) -> None:
        def test_caller() -> str:
            # Injected by the test, not read by the production identity resolver.
            return "logan@example.invalid" if request.headers.get("X-Test-Caller") == "logan" else "someone@example.invalid"

        self.client = create_app(service=ToolService(FakeStore()), caller_resolver=test_caller).test_client()
        self.headers = {"X-Test-Caller": "logan", "X-Fieldsight-Thread-Id": "bound-thread"}

    def test_extraction_uses_verified_caller_and_bound_thread(self) -> None:
        response = self.client.post("/tools/get_incident_extraction", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["result"]["normalized_fields"], {"days_away": 2})

    def test_request_cannot_choose_subject_and_requires_caller_headers(self) -> None:
        missing = self.client.post("/tools/get_incident_extraction", json={})
        self.assertEqual((missing.status_code, missing.get_json()["error"]["code"]), (401, "unauthenticated"))
        forged = self.client.post("/tools/get_incident_extraction", json={"incident_id": "another-case"}, headers=self.headers)
        self.assertEqual((forged.status_code, forged.get_json()["error"]["code"]), (400, "invalid_input"))

    def test_similar_denies_other_callers_session(self) -> None:
        other = dict(self.headers, **{"X-Test-Caller": "another"})
        denied = self.client.post("/tools/find_similar_incidents", json={"limit": 3}, headers=other)
        self.assertEqual((denied.status_code, denied.get_json()["error"]["code"]), (403, "not_entitled"))
        allowed = self.client.post("/tools/find_similar_incidents", json={"limit": 3}, headers=self.headers)
        self.assertEqual((allowed.status_code, allowed.get_json()["result"]["items"]), (200, []))

    def test_liveness_and_readiness_are_distinct(self) -> None:
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 503)

    def test_production_without_verified_identity_fails_closed(self) -> None:
        client = create_app(service=ToolService(FakeStore())).test_client()
        denied = client.post("/tools/get_incident_extraction", json={}, headers=self.headers)
        self.assertEqual((denied.status_code, denied.get_json()["error"]["code"]), (401, "unauthenticated"))


if __name__ == "__main__":
    unittest.main()
