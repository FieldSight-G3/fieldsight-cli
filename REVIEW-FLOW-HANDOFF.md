# Review flow handoff

Place `review_flow.py` and `test_review_flow.py` at the paths in this package. No existing teammate-owned file is replaced.

`submit_review()` is the Logan-owned validation boundary. Build `ReviewRequest` from an analyst's selected action only; pass `verified_reviewer_id` from an authenticated reviewer session, never from a request field. The reviewer and submitting analyst must differ. The pure `decide_review()` validator checks allowed edits and same-document citation repoints before any write.

Jenya's repository needs to implement the `ReviewStore` protocol in `fieldsight.review_flow`:

- `get_pending(queue_id)` returns a `PendingReview` based on a `pending` queue row and an immutable snapshot of the original dossier, including submitting analyst ID and citation ID to source document/chunk mapping. Existing `review_queue` rows hold only incident ID, triggers, status, and decision; `incidents.outcome` is mutable and does not replace a snapshot. This requires a repository/schema change or a reliable reference to an immutable recorded dossier.
- `record_if_pending(decision)` atomically changes `review_queue.status` and `review_queue.decision` using `UPDATE ... WHERE queue_id = :queue_id AND incident_id = :incident_id AND status = 'pending' RETURNING queue_id`. Store `decision.model_dump(mode="json")`. Return `False` if no row updated, so a second reviewer cannot overwrite the first decision. Keep the original dossier separate from the edit.

The caller handles `ReviewConflict` as an already-reviewed or missing item, and validation errors as a refused edit. The function returns only after the repository records the decision. Completing this repository adapter and verifying it with PostgreSQL is necessary before exposing the review CLI command.

Local checks from the project root:

```powershell
ruff check .\src\fieldsight\review_flow.py .\src\fieldsight\tests\test_review_flow.py
python -m pytest .\src\fieldsight\tests\test_review_flow.py .\src\fieldsight\tests\test_review_decisions.py -q
```
