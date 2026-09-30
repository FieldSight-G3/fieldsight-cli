""" shapes of packet artifact data in the ingestion pipeline: plain dicts built by our own code """

from typing import Literal, NotRequired, TypedDict

from ..schemas.corroboration import Corroboration
from ..schemas.incidents import NormalizedIncident
from .guardrails import Refusal


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


class NormalizeInput(TypedDict):
    """ what normalize reads: a packet's screened, redacted fields and narrative, and the note the narrative came from """

    fields: list[ExtractedField]
    narrative: str | None
    narrative_artifact: NotRequired[str]


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


class PhotoCorroboration(TypedDict):
    """ one photograph's verdict against the narrative, as the incident stores it for escalation """

    artifact: str
    verdict: Corroboration
    observation: str
    reason: str


class IngestedPacket(TypedDict):
    """ a packet after ingestion: its normalized record, redacted narrative and report, ready to be saved """

    incident: NormalizedIncident
    narrative: str | None
    report: IngestionReport
    withheld: list[str]
    photos: list[PhotoCorroboration]


class SubmitResult(TypedDict):
    """ what submit hands back: the new incident and its ingestion report, or the refusal that stopped it """

    incident_id: str | None
    establishment: str | None
    report: IngestionReport | None
    withheld: list[str]         # cracked strings the Prompt Attacks filter kept from the model
    photos: list[PhotoCorroboration]    # each photograph judged against the narrative (section 7 step 3)
    refusal: Refusal | None
