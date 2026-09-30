""" a packet folder through section 7's ingestion: store, crack, screen, redact, normalize, corroborate photos, report

    Ingest knows nothing about analysts or grants. The screen (the Prompt Attacks filter) is passed in by the
    harness, which also saves the result, the way run_turn is handed its workflow and answerer.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path

from ..errors import ExtractionError
from ..schemas.rule_input import R5Inputs
from ..types.artifacts import ArtifactFailure, IngestedPacket, PhotoCorroboration
from ..types.guardrails import ARTIFACT_NAME
from .artifacts.packet import crack_packet
from .artifacts.redact import redact
from .artifacts.report import ingestion_report
from .corroborate import MAX_IMAGE_BYTES, corroborate, too_large
from .normalize import normalize_chain

log = logging.getLogger(__name__)

# the floor R5 applies, so the report flags exactly what the readiness gate will
FLOOR = R5Inputs.model_fields["floor"].default
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")

# cracked strings in, the ones that passed the screen out
Screen = Callable[[dict[str, str]], dict[str, str]]


def packet_artifacts(folder: Path) -> tuple[list[Path], list[ArtifactFailure]]:
    """ the files FieldSight reads, and the rest skipped and logged, e.g. a README left in the folder """

    files = sorted(path for path in folder.iterdir() if path.is_file())
    supported = [path for path in files if re.match(ARTIFACT_NAME, path.name)]
    skipped = [ArtifactFailure(artifact=path.name, reason="unsupported artifact type") for path in files if path not in supported]
    for failure in skipped:
        log.warning("skipped artifact %s: %s", failure["artifact"], failure["reason"])
    return supported, skipped


def corroborate_photos(photos: list[Path], narrative: str | None) -> tuple[list[PhotoCorroboration], list[ArtifactFailure]]:
    """ each photo's verdict against the redacted narrative; one that's too large or can't be judged is skipped and logged """

    verdicts, failures = [], []
    for photo in photos:
        if too_large(photo):
            failures.append(ArtifactFailure(artifact=photo.name,
                                            reason=f"photo too large for the model (over {MAX_IMAGE_BYTES / 1024 / 1024:.2f} MB)"))
            continue
        try:
            verdicts.append(corroborate(photo, narrative))
        except ExtractionError as error:
            failures.append(ArtifactFailure(artifact=photo.name, reason=str(error)))
    for failure in failures:
        log.warning("skipped photo %s: %s", failure["artifact"], failure["reason"])
    return verdicts, failures


def ingest_packet(supported: list[Path], skipped: list[ArtifactFailure], *, screen: Screen) -> IngestedPacket:
    """ store and crack the forms (a malformed one is skipped and logged), screen every cracked string,
        redact what passed, normalize it in one structured-output call, then judge each photo against it """

    extraction = crack_packet([path for path in supported if path.suffix.lower() == ".pdf"])
    notes = {path.name: path.read_text(encoding="utf-8") for path in supported if path.suffix.lower() == ".txt"}

    # what the screen withholds never reaches redaction or the model
    keys = [f"{Path(field['artifact']).name}#{index}: {field['label']}" for index, field in enumerate(extraction["fields"])]
    cracked = dict(zip(keys, (field["value"] for field in extraction["fields"]))) | notes
    screened = screen(cracked)
    fields = [field for key, field in zip(keys, extraction["fields"]) if key in screened]
    kept_notes = [name for name in notes if name in screened]

    redacted = redact(fields, "\n\n".join(notes[name] for name in kept_notes) or None)
    incident = normalize_chain().invoke({"fields": redacted["fields"], "narrative": redacted["narrative"],
                                         "narrative_artifact": ", ".join(kept_notes)})
    photos, photo_failures = corroborate_photos([path for path in supported if path.suffix.lower() in PHOTO_SUFFIXES],
                                                redacted["narrative"])
    report = ingestion_report({"artifacts": [path.name for path in supported], "fields": extraction["fields"],
                               "failures": skipped + extraction["failures"] + photo_failures}, FLOOR)
    return IngestedPacket(incident=incident, narrative=redacted["narrative"], report=report,
                          withheld=[source for source in cracked if source not in screened], photos=photos)
