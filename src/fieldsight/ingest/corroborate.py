""" corroborate a photograph: the multimodal model judges it against the packet's redacted narrative (section 7 step 3)

    The multimodal model takes images through Converse. A photo over Bedrock's image limit is shrunk to fit before
    it's sent; one that still won't fit is a typed failure the caller skips and logs, so the ingestion report says so.
"""

import base64
import io
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image, ImageOps

from ..aws import clients
from ..errors import ExtractionError
from ..prompts import PROMPTS
from ..schemas.corroboration import PhotoVerdict
from ..types.artifacts import PhotoCorroboration

# Bedrock Converse refuses an image over 3.75 MB
MAX_IMAGE_BYTES = int(3.75 * 1024 * 1024)
MIME_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


# a photo over the limit is shrunk to this longest side, which keeps the detail a verdict rests on
MAX_SIDE_PX = 2048


def image_block(photo: Path) -> dict:
    """ the photo as Converse takes it: as it is when it fits, shrunk to a JPEG when it's over the limit """

    data, mime_type = photo.read_bytes(), MIME_TYPES[photo.suffix.lower()]
    if len(data) > MAX_IMAGE_BYTES:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))  # a phone photo keeps its upright orientation
        image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
        shrunk = io.BytesIO()
        image.convert("RGB").save(shrunk, "JPEG", quality=85)
        data, mime_type = shrunk.getvalue(), "image/jpeg"
    if len(data) > MAX_IMAGE_BYTES:
        raise ExtractionError(f"{photo.name} is over the model's image limit even shrunk")
    return {"type": "image", "base64": base64.b64encode(data).decode("ascii"), "mime_type": mime_type}


def corroborate(photo: Path, narrative: str | None) -> PhotoCorroboration:
    """ one photo's verdict; one retry with the validation error, then a typed failure (section 13) """

    model = clients.chat_model(multimodal=True).with_structured_output(PhotoVerdict)
    image = image_block(photo)
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
        # the reminder rides in the system message: as a user turn the Prompt Attacks filter can block it as an injection
        messages[0] = SystemMessage(f"{PROMPTS['corroborator']}\n\nYour last verdict was invalid: {problem}. "
                                    "Return one that matches the PhotoVerdict schema.")
    raise ExtractionError(f"no valid corroboration verdict for {photo.name} after one retry")
