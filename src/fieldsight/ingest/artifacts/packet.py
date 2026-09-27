""" crack a packet's form artifacts; malformed ones are logged and skipped """

import logging
from pathlib import Path

from ...errors import ExtractionError
from ...types.artifacts import ARTIFACT_FAILURE, ExtractedField, PacketExtraction
from ..crack import crack
from .fields import extract_form_fields
from .storage import upload_artifact

log = logging.getLogger(__name__)


def crack_artifact(path: Path) -> list[ExtractedField]:
    """ store one artifact, crack it with Textract, and read its form fields """

    artifact = upload_artifact(path)
    return extract_form_fields(crack(artifact["key"], token=artifact["digest"]), artifact["key"])


def crack_packet(paths: list[Path]) -> PacketExtraction:
    """ every artifact's fields; failures are recorded and skipped so the incident proceeds """

    fields, failures = [], []
    for path in paths:
        try:
            fields += crack_artifact(path)
        except ExtractionError as error:
            log.warning("skipped artifact %s: %s", path.name, error)
            failures.append(ARTIFACT_FAILURE.validate_python({"artifact": path.name, "reason": str(error)}))
    return {"artifacts": [path.name for path in paths], "fields": fields, "failures": failures}
