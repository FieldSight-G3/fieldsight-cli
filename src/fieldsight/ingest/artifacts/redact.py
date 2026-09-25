""" strip PII from packet content before anything reaches a model """

import re

from ...types.artifacts import REDACTED_SPAN, ExtractedField, Redacted, RedactedSpan

# Form 301 labels whose whole value is personal information: names, addresses, date of birth, contact details
PII_LABEL = re.compile(r"\b(name|street|address|city|zip|phone|date of birth|ssn|social security|e-?mail|completed by)\b")
# only Form 301 field 1 holds the employee's name; other labels mention "employee" but hold facts about the incident
EMPLOYEE_NAME_LABEL = re.compile(r"\bfull name\b")

SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")


def is_pii_label(label: str) -> bool:
    """ whether a form field's label marks it as personal information """

    return PII_LABEL.search(label.lower()) is not None


def patterns(names: set[str]) -> list[tuple[str, re.Pattern]]:
    """ what gets masked in free text: SSNs, emails, phone numbers, and the employee's names """

    found = [("ssn", SSN), ("email", EMAIL), ("phone", PHONE)]
    if names:
        found.append(("name", re.compile(r"\b(" + "|".join(map(re.escape, sorted(names))) + r")\b", re.IGNORECASE)))
    return found


def scrub_text(text: str, names: set[str], where: str) -> tuple[str, list[RedactedSpan]]:
    """ the text with every match masked, and where each one was, as offsets in the original text """

    # earliest first, and the longest match where two start together, so an email wins over the name inside it
    matches = sorted(((m.start(), m.end(), kind) for kind, pattern in patterns(names) for m in pattern.finditer(text)),
                     key=lambda match: (match[0], -match[1]))
    parts, spans, cursor = [], [], 0
    for start, end, kind in matches:
        if start < cursor:      # overlaps a match already masked
            continue
        parts += [text[cursor:start], f"[REDACTED_{kind.upper()}]"]
        spans.append(REDACTED_SPAN.validate_python({"kind": kind, "where": where, "start": start, "end": end}))
        cursor = end
    return "".join(parts) + text[cursor:], spans


def redact(fields: list[ExtractedField], narrative: str | None) -> Redacted:
    """ drop PII fields, then scrub what's left, including the employee's name from the narrative; reports every removed span """

    dropped = [field for field in fields if is_pii_label(field["label"])]
    spans = [REDACTED_SPAN.validate_python({"kind": "field", "where": f["label"], "start": 0, "end": len(f["value"])}) for f in dropped]

    names = {
        word
        for field in fields
        if EMPLOYEE_NAME_LABEL.search(field["label"])
        for word in re.findall(r"[A-Za-z][A-Za-z'-]+", field["value"])
    }

    kept = []
    for field in fields:
        if field in dropped:
            continue
        value, found = scrub_text(field["value"], names, field["label"])
        kept.append({**field, "value": value})
        spans += found
    if narrative:
        narrative, found = scrub_text(narrative, names, "narrative")
        spans += found
    return {"fields": kept, "narrative": narrative, "spans": spans}
