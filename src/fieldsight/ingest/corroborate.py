""" corroborate a photograph: the multimodal model judges it against the packet's redacted narrative (section 7 step 3)

    The reasoning tier takes images through Converse. A photo over Bedrock's image limit is never sent; the caller
    skips and logs it, so the ingestion report says it was too large.
"""

import base64
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from ..aws import clients
from ..errors import ExtractionError
from ..prompts import PROMPTS
from ..schemas.corroboration import PhotoVerdict
from ..types.artifacts import PhotoCorroboration

# Bedrock Converse refuses an image over 3.75 MB
MAX_IMAGE_BYTES = int(3.75 * 1024 * 1024)
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def too_large(photo: Path) -> bool:
    return photo.stat().st_size > MAX_IMAGE_BYTES


def corroborate(photo: Path, narrative: str | None) -> PhotoCorroboration:
    """ one photo's verdict; one retry with the validation error, then a typed failure (section 13) """

    model = clients.chat_model().with_structured_output(PhotoVerdict)
    image = {"type": "image", "base64": base64.b64encode(photo.read_bytes()).decode("ascii"),
             "mime_type": MIME_TYPES[photo.suffix.lower()]}
    messages = [SystemMessage(PROMPTS["corroborator"]),
                HumanMessage(content=[{"type": "text", "text": f"Narrative:\n{narrative or '(the packet has no narrative)'}"},
                                      image])]
    for _ in range(2):
        try:
            verdict = model.invoke(messages)
        except ValueError as error:
            problem = str(error)
        else:
            if verdict:
                return PhotoCorroboration(artifact=photo.name, **verdict.model_dump())
            problem = "no verdict was returned"
        messages.append(HumanMessage(f"That verdict was invalid: {problem}. Return one that matches the PhotoVerdict schema."))
    raise ExtractionError(f"no valid corroboration verdict for {photo.name} after one retry")
