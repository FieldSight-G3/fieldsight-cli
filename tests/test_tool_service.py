"""No tool may select the subject incident or skip the per-call access check."""

import unittest
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from fieldsight.errors import ToolDenied
from fieldsight.schemas.incidents import SimilarCandidate
from fieldsight.tools.service import ToolService

CASE_ID = UUID("00000000-0000-0000-0000-000000000123")


class FakeStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def extraction(self, verified_email: str, thread_id: str) -> dict[str, Any]:
        self.calls.append(("extraction", verified_email, thread_id))
        if verified_email != "alice@example.invalid" or thread_id != "alice-case":
            raise ToolDenied("not_entitled", "Not this session")
        return {"normalized_fields": {"days_away": 2}}

    def similar(self, verified_email: str, thread_id: str, limit: int) -> list[SimilarCandidate]:
        self.calls.append(("similar", verified_email, thread_id))
        if verified_email != "alice@example.invalid" or thread_id != "alice-case":
            raise ToolDenied("not_entitled", "Not this session")
        return [SimilarCandidate(incident_id=CASE_ID, outcome={"recordable": True}, deciding_rule="R1", similarity_score=0.9, matching_narrative_span="Tripped near equipment")][:limit]


class ToolServiceTests(unittest.TestCase):
    def test_read_tools_bind_session_and_caller_on_each_call(self) -> None:
        store = FakeStore()
        service = ToolService(store)
        extraction = service.get_incident_extraction("alice@example.invalid", "alice-case", {})
        similar = service.find_similar_incidents("alice@example.invalid", "alice-case", {"limit": 1})
        self.assertTrue(extraction.ok)
        assert similar.result is not None
        self.assertEqual(similar.result["items"][0]["deciding_rule"], "R1")
        self.assertEqual(store.calls, [("extraction", "alice@example.invalid", "alice-case"), ("similar", "alice@example.invalid", "alice-case")])

    def test_model_supplied_incident_or_caller_is_rejected(self) -> None:
        service = ToolService(FakeStore())
        for payload in ({"incident_id": str(CASE_ID)}, {"analyst_id": "alice"}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                service.get_incident_extraction("alice@example.invalid", "alice-case", payload)
        with self.assertRaises(ValidationError):
            service.find_similar_incidents("alice@example.invalid", "alice-case", {"limit": 8})

    def test_store_denies_wrong_session_on_each_call(self) -> None:
        service = ToolService(FakeStore())
        for name in ("get_incident_extraction", "find_similar_incidents"):
            with self.subTest(name=name), self.assertRaises(ToolDenied):
                getattr(service, name)("alice@example.invalid", "someone-elses-case", {})


if __name__ == "__main__":
    unittest.main()
