""" the one PII redactor, applied to everything written after ingest: log lines and run records

    It reuses ingest's scrub_text rather than a second set of patterns. Ingest already dropped the
    Form 301 PII fields and masked the employee's name, so what can still leak downstream is an
    SSN, email or phone number echoed back in free text; those are masked wherever they appear.
"""

from collections.abc import Mapping
from typing import Any

from ..ingest.artifacts.redact import scrub_text


def redact_text(text: str, where: str = "text") -> str:
    """ text with any SSN, email or phone number masked as [REDACTED_KIND] """

    return scrub_text(text, set(), where)[0]


def redact_payload(value: Any) -> Any:
    """ a JSON-shaped value with every string redacted; keys, numbers and structure are kept """

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {key: redact_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_payload(item) for item in value]
    return value
