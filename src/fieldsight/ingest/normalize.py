""" normalize a packet: one structured-output call from its redacted fields and narrative to a NormalizedIncident

    The model reads the values; it never scores them. Each field's confidence and source artifact are set here
    from the Textract fields it can come from, so an illegible form field keeps its low confidence whatever the
    model read, and a model's self-reported confidence is never an input.
"""

import json
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from ..aws import clients
from ..errors import ExtractionError
from ..prompts import PROMPTS
from ..schemas.incidents import NormalizedIncident
from ..types.artifacts import ExtractedField, NormalizeInput

# the Form 301 fields a value can be read from, matched on label text; any other field can only come from the narrative
FORM_SOURCES: dict[str, tuple[str, ...]] = {
    "incident_at": ("date of injury", "time of event"),
    "event_type": ("hospitalized overnight",),
    "admission_reason": ("hospitalized overnight",),
    "treatments": ("what was the injury",),
    "death": ("date of death",),
}

# the fields that describe one kind of event only, and that event
EVENT_DETAILS = {"admission_reason": "inpatient_hospitalization", "amputation_detail": "amputation"}

# a supervisor note is typed text, not OCR, so what's read from it is exact
NARRATIVE_CONFIDENCE = 1.0


def draft(packet: NormalizeInput) -> NormalizedIncident:
    """ the model's reading of the packet; one retry with the validation error, then a typed failure (section 13) """

    model = clients.chat_model().with_structured_output(NormalizedIncident)
    content = json.dumps({"fields": [{"label": f["label"], "value": f["value"]} for f in packet["fields"]],
                          "narrative": packet.get("narrative")})
    messages = [SystemMessage(PROMPTS["normalizer"]), HumanMessage(content)]
    for _ in range(2):
        try:
            record = model.invoke(messages)
        except ValueError as error:
            problem = str(error)
        else:
            if record:
                return record
            problem = "no record was returned"
        messages.append(HumanMessage(f"That record was invalid: {problem}. Return one that matches the NormalizedIncident schema."))
    raise ExtractionError("normalize returned no valid record after one retry")


def form_fields(fields: list[ExtractedField], name: str) -> list[ExtractedField]:
    """ the extracted form fields a normalized field can be read from """

    return [field for field in fields if any(label in field["label"] for label in FORM_SOURCES.get(name, ()))]


def attach_provenance(packet: dict) -> NormalizedIncident:
    """ each value's confidence and source from the extraction, never the model; a value with no source is dropped """

    values = packet["draft"].model_dump(exclude={"incident_id", "confidences", "sources"})
    # each detail belongs to one event type; a model fills an enum it was told to leave null, so the code decides
    for detail, event in EVENT_DETAILS.items():
        if values.get("event_type") != event:
            values[detail] = None
    confidences: dict[str, float] = {}
    sources: dict[str, str] = {}
    for name, value in values.items():
        if value is None:
            continue
        if found := form_fields(packet["fields"], name):
            # the weakest reading governs, so an illegible date of injury stays below the floor
            weakest = min(found, key=lambda field: field["confidence"])
            confidences[name], sources[name] = weakest["confidence"], weakest["artifact"]
        elif packet.get("narrative"):
            confidences[name], sources[name] = NARRATIVE_CONFIDENCE, packet.get("narrative_artifact") or "narrative"
        else:
            # nothing in the packet could have said it, so it's missing, never a default
            values[name] = None
            continue
        if isinstance(value, datetime) and value.tzinfo is None:
            values[name] = value.replace(tzinfo=UTC)
    return NormalizedIncident(incident_id="", **values, confidences=confidences, sources=sources)


def normalize_chain() -> Runnable[NormalizeInput, NormalizedIncident]:
    """ a packet's screened, redacted fields and narrative in, its NormalizedIncident out """

    return RunnablePassthrough.assign(draft=RunnableLambda(draft)) | RunnableLambda(attach_provenance)
