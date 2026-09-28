"""Review-card decisions and edits are validated without touching the DB."""

import unittest
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from fieldsight.harness.review_decisions import (
    CitationReference,
    CitationRepoint,
    ReviewAction,
    ReviewContext,
    ReviewEdit,
    ReviewRequest,
    decide_review,
)

SUBMITTER = UUID("00000000-0000-0000-0000-000000000001")
REVIEWER = UUID("00000000-0000-0000-0000-000000000002")
CASE = UUID("00000000-0000-0000-0000-000000000003")
QUEUE = UUID("00000000-0000-0000-0000-000000000004")


def context() -> ReviewContext:
    return ReviewContext(
        queue_id=QUEUE, incident_id=CASE,
        submitting_analyst_id=SUBMITTER, reviewer_id=REVIEWER,
        decided_at=datetime(2026, 9, 24, 12, tzinfo=UTC),
    )


class ReviewDecisionTests(unittest.TestCase):
    def test_approve_and_reject_record_identity_time_and_action(self) -> None:
        cases: tuple[tuple[ReviewAction, str | None, str], ...] = (
            ("approve", None, "approved"), ("reject", "Incorrect evidence", "rejected")
        )
        for action, reason, status in cases:
            with self.subTest(action=action):
                request = ReviewRequest(action=action, reason=reason)
                result = decide_review(request, context(), original_payload={"outcome": "R1"}, original_citations={})
                self.assertEqual(result.status, status)
                self.assertEqual(result.reviewer_id, REVIEWER)
                self.assertEqual(result.decided_at, context().decided_at)
                self.assertEqual(result.model_dump(mode="json")["action"], action)

    def test_edit_keeps_original_dossier_and_only_changes_allowed_fields(self) -> None:
        original: dict[str, Any] = {"narrative": "original", "outcome": {"rule": "R1", "days": 30}}
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(narrative="clearer wording", note="Checked"))
        result = decide_review(request, context(), original_payload=original, original_citations={})
        original["outcome"]["days"] = 45
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.original_payload["outcome"]["days"], 30)
        assert result.edit is not None
        self.assertEqual(result.edit.narrative, "clearer wording")
        self.assertEqual(result.model_dump(mode="json")["original_payload"]["narrative"], "original")
        with self.assertRaises(ValidationError):
            ReviewEdit.model_validate({"rule_outcome": "not_recordable"})

    def test_edit_repoints_only_to_a_different_chunk_in_the_same_document(self) -> None:
        citation = {"ref-2": CitationReference(document_id="CFR-1904", chunk_id="chunk-1")}
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(
            citation_repoints=[CitationRepoint(citation_id="ref-2", replacement_chunk_id="chunk-2")]
        ))
        resolver = {"chunk-2": "CFR-1904", "other": "CFR-269"}.get
        result = decide_review(request, context(), original_payload={}, original_citations=citation, source_for_chunk=resolver)
        assert result.edit is not None
        self.assertEqual(result.edit.citation_repoints[0].replacement_chunk_id, "chunk-2")
        for bad_chunk in ("other", "missing", "chunk-1"):
            with self.subTest(chunk=bad_chunk), self.assertRaises(ValueError):
                bad = request.model_copy(update={"edit": ReviewEdit(
                    citation_repoints=[CitationRepoint(citation_id="ref-2", replacement_chunk_id=bad_chunk)]
                )})
                decide_review(bad, context(), original_payload={}, original_citations=citation, source_for_chunk=resolver)

    def test_missing_and_duplicate_citations_are_refused(self) -> None:
        repoint = CitationRepoint(citation_id="ref-1", replacement_chunk_id="new")
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(citation_repoints=[repoint]))
        with self.assertRaises(ValueError):
            decide_review(request, context(), original_payload={}, original_citations={}, source_for_chunk=lambda _: "CFR-1904")
        duplicate = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(citation_repoints=[repoint, repoint]))
        with self.assertRaises(ValueError):
            decide_review(duplicate, context(), original_payload={}, original_citations={"ref-1": CitationReference(document_id="CFR-1904", chunk_id="old")}, source_for_chunk=lambda _: "CFR-1904")

    def test_request_requires_matching_edit_or_rejection_reason(self) -> None:
        for data in ({"action": "edit_then_approve"}, {"action": "reject"}, {"action": "approve", "edit": {"note": "change"}}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                ReviewRequest.model_validate(data)

    def test_self_review_and_naive_timestamp_are_refused(self) -> None:
        with self.assertRaises(ValidationError):
            ReviewContext.model_validate({**context().model_dump(), "reviewer_id": SUBMITTER})
        with self.assertRaises(ValidationError):
            ReviewContext.model_validate({**context().model_dump(), "decided_at": datetime(2026, 9, 24)})  # noqa: DTZ001


if __name__ == "__main__":
    unittest.main()
