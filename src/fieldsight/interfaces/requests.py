""" the CLI's arguments shaped into what the harness takes; nothing is checked here, the harness validates """

from ..harness.escalation.review import CitationRepoint, ReviewEdit, ReviewRequest


def turn_request(command: str, incident_id: str, question: str | None = None) -> dict:
    """ the raw request run_turn validates at stage 1 """

    return {"command": command, "incident_id": incident_id, **({"question": question} if question is not None else {})}


def review_request(action: str, reason: str | None, narrative: str | None, note: str | None,
                   repoints: list[str] | None) -> ReviewRequest:
    """ the reviewer's action; CITATION=CHUNK pairs become repoints, which decide_review checks against the source """

    citation_repoints = [CitationRepoint(citation_id=citation, replacement_chunk_id=chunk)
                         for citation, _, chunk in (pair.partition("=") for pair in repoints or [])]
    edit = (ReviewEdit(narrative=narrative, note=note, citation_repoints=citation_repoints)
            if action == "edit_then_approve" else None)
    return ReviewRequest(action=action, edit=edit, reason=reason)
