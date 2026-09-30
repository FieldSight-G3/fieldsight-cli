"""§11: one redactor, used everywhere; log lines and run-record payloads are scrubbed before they are written."""

import json
import logging

from fieldsight.ingest.artifacts.redact import scrub_text
from fieldsight.logging_context import CorrelationFilter, JsonFormatter
from fieldsight.security import redaction
from fieldsight.security.redaction import redact_payload, redact_text

LEAKY = "Call Marcus at 571-555-0142 or m.whitfield@example.com; SSN 123-45-6789."


def test_redact_text_masks_ssn_email_and_phone():
    masked = redact_text(LEAKY)
    assert "571-555-0142" not in masked and "m.whitfield@example.com" not in masked and "123-45-6789" not in masked
    assert masked.count("[REDACTED_") == 3
    assert redact_text("Days away: 176, returned 2026-08-21.") == "Days away: 176, returned 2026-08-21."


def test_it_is_the_ingest_redactor_not_a_second_one():
    assert redaction.scrub_text is scrub_text
    assert redact_text(LEAKY) == scrub_text(LEAKY, set(), "text")[0]


def test_payloads_keep_structure_and_non_text_values():
    payload = {"items": [{"note": LEAKY, "days_away": 176, "confident": True, "score": 0.93}], "missing": None}

    cleaned = redact_payload(payload)

    assert cleaned["items"][0]["days_away"] == 176 and cleaned["items"][0]["confident"] is True
    assert cleaned["items"][0]["score"] == 0.93 and cleaned["missing"] is None
    assert "123-45-6789" not in json.dumps(cleaned)
    assert redact_payload(None) is None


def test_log_lines_and_tracebacks_are_redacted():
    def line(record: logging.LogRecord) -> dict:
        CorrelationFilter().filter(record)
        return json.loads(JsonFormatter().format(record))

    message = logging.LogRecord("fieldsight.test", logging.INFO, __file__, 1, "caller %s", ("m.whitfield@example.com",), None)
    assert "example.com" not in line(message)["message"]

    try:
        raise ValueError(f"bad row for SSN {'123-45-6789'}")
    except ValueError as error:
        failed = logging.LogRecord("fieldsight.test", logging.ERROR, __file__, 1, "failed", None, (type(error), error, error.__traceback__))
    assert "123-45-6789" not in line(failed)["exception"]


def test_extra_fields_reach_the_log_redacted():
    from uuid import UUID

    record = logging.LogRecord("fieldsight.test", logging.WARNING, __file__, 1, "retrieval refused", None, None)
    record.reason = "below_threshold"
    record.question = "Is Marcus (571-555-0142) covered?"
    record.searched = [{"doc_type": "regulation", "incident": UUID(int=7)}]
    CorrelationFilter().filter(record)

    line = json.loads(JsonFormatter().format(record))

    assert line["extra"]["reason"] == "below_threshold"
    assert "571-555-0142" not in line["extra"]["question"] and "[REDACTED_PHONE]" in line["extra"]["question"]
    assert line["extra"]["searched"][0]["incident"] == str(UUID(int=7))
    assert "correlation_id" not in line["extra"]
