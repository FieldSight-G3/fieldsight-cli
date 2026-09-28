""" shapes of packet artifact data in the ingestion pipeline: plain dicts built by our own code """

from typing import Literal, TypedDict


class StoredArtifact(TypedDict):
    """ a packet artifact once it is in S3, keyed by its content hash """

    name: str
    digest: str
    key: str


class ExtractedField(TypedDict):
    """ one filled-in form field, traced to the artifact and page it came from """

    label: str
    value: str
    confidence: float
    artifact: str
    page: int


RedactionKind = Literal["field", "name", "ssn", "email", "phone"]


class RedactedSpan(TypedDict):
    """ where something was removed; never the removed text itself, since that is the PII """

    kind: RedactionKind
    where: str          # the field label, or "narrative"
    start: int
    end: int


class Redacted(TypedDict):
    """ a packet's fields and narrative after redaction, with the spans that were removed """

    fields: list[ExtractedField]
    narrative: str | None
    spans: list[RedactedSpan]


class ArtifactFailure(TypedDict):
    """ an artifact that was skipped, and why """

    artifact: str
    reason: str


class PacketExtraction(TypedDict):
    """ what came out of a packet's artifacts, and which were skipped """

    artifacts: list[str]
    fields: list[ExtractedField]
    failures: list[ArtifactFailure]


class IngestionReport(TypedDict):
    """ the ingestion report: artifacts processed, fields extracted, fields below the floor, failures """

    artifacts_processed: int
    fields_extracted: int
    fields_below_floor: list[str]
    failures: list[ArtifactFailure]
