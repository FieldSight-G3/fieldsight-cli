"""The review path uses a trusted identity and saves a queue decision once."""

import unittest
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError

from fieldsight.harness.escalation.review import (
    CitationReference,
    CitationRepoint,
    PendingReview,
    ReviewConflict,
    ReviewDecision,
    ReviewEdit,
    ReviewNotEntitled,
    ReviewRequest,
    document_for_chunk,
    submit_review,
)

QUEUE = UUID("00000000-0000-0000-0000-000000000004")
CASE = UUID("00000000-0000-0000-0000-000000000003")
SUBMITTER = UUID("00000000-0000-0000-0000-000000000001")
REVIEWER = UUID("00000000-0000-0000-0000-000000000002")
DECIDED_AT = datetime(2026, 9, 27, 12, tzinfo=UTC)


class FakeReviewStore:
    def __init__(self) -> None:
        self.pending: PendingReview | None = PendingReview(
            queue_id=QUEUE,
            incident_id=CASE,
            submitting_analyst_id=SUBMITTER,
            original_payload={"narrative": "Original", "outcome": {"rule": "R1"}},
            original_citations={"ref-1": CitationReference(document_id="CFR-1904", chunk_id="old")},
        )
        self.saved: ReviewDecision | None = None
        self.can_save = True
        self.entitled = {REVIEWER, SUBMITTER}

    def get_pending(self, queue_id: UUID) -> PendingReview | None:
        return self.pending if self.pending is not None and self.pending.queue_id == queue_id else None

    def reviewer_entitled(self, reviewer_id: UUID, incident_id: UUID) -> bool:
        return reviewer_id in self.entitled and incident_id == CASE

    def record_if_pending(self, decision: ReviewDecision) -> bool:
        if (not self.can_save or self.pending is None or decision.queue_id != self.pending.queue_id or decision.incident_id != self.pending.incident_id):
            return False
        self.saved = decision
        self.pending = None
        return True


class ReviewFlowTests(unittest.TestCase):
    def test_approve_uses_verified_reviewer_and_original_snapshot(self) -> None:
        store = FakeReviewStore()
        decision = submit_review(ReviewRequest(action="approve"), queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store, decided_at=DECIDED_AT)
        self.assertEqual(decision.status, "approved")
        self.assertEqual(decision.reviewer_id, REVIEWER)
        self.assertEqual(decision.decided_at, DECIDED_AT)
        self.assertEqual(decision.original_payload["outcome"], {"rule": "R1"})
        self.assertIs(store.saved, decision)
        with self.assertRaises(ReviewConflict):
            submit_review(ReviewRequest(action="reject", reason="wrong"), queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store)

    def test_rejection_is_recorded_and_self_review_cannot_write(self) -> None:
        store = FakeReviewStore()
        with self.assertRaises(ValidationError):
            submit_review(ReviewRequest(action="approve"), queue_id=QUEUE, verified_reviewer_id=SUBMITTER, store=store, decided_at=DECIDED_AT)
        self.assertIsNone(store.saved)
        decision = submit_review(ReviewRequest(action="reject", reason="Unsupported claim"), queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store, decided_at=DECIDED_AT)
        self.assertEqual(decision.status, "rejected")
        self.assertEqual(decision.reason, "Unsupported claim")

    def test_edit_only_allows_same_document_citation(self) -> None:
        store = FakeReviewStore()
        repoint = CitationRepoint(citation_id="ref-1", replacement_chunk_id="other")
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(narrative="Clearer", citation_repoints=[repoint]))
        with self.assertRaises(ValueError):
            submit_review(request, queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store, source_for_chunk=lambda _: "CFR-269")
        self.assertIsNone(store.saved)
        decision = submit_review(request, queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store, source_for_chunk=lambda _: "CFR-1904")
        self.assertEqual(decision.action, "edit_then_approve")
        self.assertEqual(decision.original_payload["narrative"], "Original")
        assert decision.edit is not None
        self.assertEqual(decision.edit.narrative, "Clearer")

    def test_missing_item_and_concurrent_decision_fail_closed(self) -> None:
        store = FakeReviewStore()
        with self.assertRaises(ReviewConflict):
            submit_review(ReviewRequest(action="approve"), queue_id=CASE, verified_reviewer_id=REVIEWER, store=store)
        store.can_save = False
        with self.assertRaises(ReviewConflict):
            submit_review(ReviewRequest(action="approve"), queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store)
        self.assertIsNone(store.saved)

    def test_reviewer_without_a_grant_is_denied_before_any_write(self) -> None:
        store = FakeReviewStore()
        store.entitled = {SUBMITTER}
        with self.assertRaises(ReviewNotEntitled):
            submit_review(ReviewRequest(action="approve"), queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store)
        self.assertIsNone(store.saved)
        self.assertIsNotNone(store.pending)

    def test_document_for_chunk_reads_the_corpus_chunk_id_format(self) -> None:
        self.assertEqual(document_for_chunk("CFR-1904-0123456789ab"), "CFR-1904")
        self.assertEqual(document_for_chunk("LOI-PACK-ffffffffffff"), "LOI-PACK")
        for chunk_id in ("CFR-1904", "CFR-1904-0123456789AB", "CFR-1904-0123456789a", "-0123456789ab", "old"):
            self.assertIsNone(document_for_chunk(chunk_id), chunk_id)


    def _dossier_store(self) -> FakeReviewStore:
        store = FakeReviewStore()
        assert store.pending is not None
        store.pending = store.pending.model_copy(update={"original_payload": {
            "recordability": {"proposal": {"outcome": "recordable", "log_column": "column_H", "rationale": "2 days away [1]"}},
            "reportability": {"proposal": {"rationale": "Not reportable: admitted for observation only; 24-hour clock does not apply"}},
        }})
        return store

    def test_narrative_edit_may_reword_around_the_determinations(self) -> None:
        store = self._dossier_store()
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(
            narrative="Recordable, Column H, with 2 days away. Not reportable: the stay was observation only (24 h clock n/a)."))
        decision = submit_review(request, queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store, decided_at=DECIDED_AT)
        self.assertEqual(decision.action, "edit_then_approve")

    def test_narrative_edit_cannot_change_an_outcome_period_or_date(self) -> None:
        for narrative in ("Not recordable.", "Recordable in column I.", "Reportable within 24 hours.", "Recordable with 3 days away.", "Injured on 2026-02-01."):
            with self.subTest(narrative=narrative):
                store = self._dossier_store()
                request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(narrative=narrative))
                with self.assertRaisesRegex(ValueError, "not change a determination"):
                    submit_review(request, queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store)
                self.assertIsNone(store.saved)

    def test_a_note_is_not_held_to_the_determination_check(self) -> None:
        store = self._dossier_store()
        request = ReviewRequest(action="edit_then_approve", edit=ReviewEdit(note="Site lead thinks 3 days; left the rule outcome as computed."))
        self.assertEqual(submit_review(request, queue_id=QUEUE, verified_reviewer_id=REVIEWER, store=store).status, "approved")


if __name__ == "__main__":
    unittest.main()
