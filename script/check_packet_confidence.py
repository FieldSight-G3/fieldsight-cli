""" show what Textract reads in a packet's PDFs: every line of text, the form fields it paired up, and its
    answer to each Form 301 question, each with a confidence

    uses Textract's synchronous API on the file's bytes, so nothing is uploaded and no bucket is needed;
    that API only takes single-page documents, which the packet PDFs are. Needs AWS access to Textract.

    run from the repo root:
        python script/check_packet_confidence.py                    the handwritten packet, inc-0413 (P3)
        python script/check_packet_confidence.py packets/inc-0411   any other packet
"""

import sys
from pathlib import Path

from fieldsight.aws.textract import analyze_bytes
from fieldsight.config import settings
from fieldsight.ingest.artifacts.fields import extract_form_fields
from fieldsight.ingest.blocks import index_blocks, related

PACKETS = Path(__file__).resolve().parents[1] / "packets"

# P3: filled in by hand and scanned; the date of injury should read below the floor, its neighbours above
HANDWRITTEN = PACKETS / "inc-0413"

# Form 301's questions by what they answer; the synchronous API takes at most 15 per page
QUERIES = {
    "full_name": "What is the employee's full name?",
    "date_of_birth": "What is the employee's date of birth?",
    "date_hired": "What is the date the employee was hired?",
    "sex": "Is the employee male or female?",
    "physician": "What is the name of the physician or other health care professional?",
    "facility": "Where was treatment given away from the worksite?",
    "emergency_room": "Was the employee treated in an emergency room?",
    "hospitalized": "Was the employee hospitalized overnight as an in-patient?",
    "case_number": "What is the case number from the log?",
    "incident_date": "What is the date of injury or illness?",
    "work_began": "What time did the employee begin work?",
    "incident_time": "What is the time of the event?",
    "activity": "What was the employee doing just before the incident occurred?",
    "what_happened": "What happened? How did the injury occur?",
    "injury": "What was the injury or illness, and what part of the body was affected?",
}


def floor_flag(confidence: float) -> str:
    return "  BELOW FLOOR" if confidence < settings.confidence_floor else ""


def answers(blocks: list[dict]) -> list[tuple[str, str, float]]:
    """ each query's alias, Textract's answer (empty when it found none), and the answer's confidence """

    by_id = index_blocks(blocks)
    found = []
    for block in blocks:
        if block.get("BlockType") == "QUERY":
            results = related(block, by_id, "ANSWER")
            best = max(results, key=lambda result: result.get("Confidence", 0.0), default=None)
            found.append((block["Query"]["Alias"], best["Text"] if best else "", best["Confidence"] / 100 if best else 0.0))
    return found


def inspect(pdf: Path) -> None:
    blocks = analyze_bytes(pdf.read_bytes(), queries=QUERIES)

    print(f"\n=== {pdf.name}")
    for page in sorted({block.get("Page", 1) for block in blocks}):
        print(f"\n--- page {page}: lines")
        for block in blocks:
            if block.get("BlockType") == "LINE" and block.get("Page", 1) == page:
                print(f"  {block['Confidence']:5.1f}  {block['Text']}")

    print("\n--- form fields (label = value, the weaker of the two confidences)")
    for field in extract_form_fields(blocks, pdf.name):
        print(f"  p{field['page']}  {field['confidence']:.2f}  {field['label']} = {field['value']!r}{floor_flag(field['confidence'])}")

    print("\n--- queries (alias = answer)")
    for alias, answer, confidence in answers(blocks):
        print(f"  {confidence:.2f}  {alias} = {answer!r}{floor_flag(confidence)}")


if __name__ == "__main__":
    for folder in [Path(arg) for arg in sys.argv[1:]] or [HANDWRITTEN]:
        for pdf in sorted(folder.glob("*.pdf")):
            inspect(pdf)
