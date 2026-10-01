""" stages 1 to 3, before any worker runs: input validation, the Prompt Attacks filter, the readiness gate """

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from ...aws import clients
from ...aws.guardrails import prompt_attack_detected, screen
from ...prompts import PROMPTS
from ...rules.confidence import confidence_floor
from ...rules.engine import create_invocation
from ...schemas.incidents import NormalizedIncident
from ...schemas.readiness import ReadinessClassification, ReadinessLabel
from ...schemas.rule_input import R5Inputs
from ...types.guardrails import TURN_REQUEST, GuardrailEvent, Route
from ..escalation.review import ReviewRequest
from .common import emit, refuse

# the fields every classify turn needs before a worker is dispatched
REQUIRED_FIELDS = ("work_related", "new_case", "incident_at", "event_type")

# what each label leads to; the readiness check can turn run_workflow into route_to_analyst, never the reverse
ROUTES: dict[str, Route] = {"policy_question": "answer_from_retrieval", "classify": "run_workflow", "action": "refuse", "out_of_scope": "refuse"}


def classify(question: str) -> ReadinessLabel:
    """ the fast model's label; the deterministic check after it decides whether a classify turn goes on """

    model = clients.chat_model(fast=True).with_structured_output(ReadinessClassification)
    return model.invoke([SystemMessage(PROMPTS["readiness"]), HumanMessage(question)]).label


def validate_request(raw: dict, *, correlation_id: str) -> dict:
    """ stage 1, before any model call: the typed request, or the refusal naming the field that failed; and the events """

    events: list[GuardrailEvent] = []
    try:
        request = TURN_REQUEST.validate_python(raw)
    except ValidationError as error:
        problem = error.errors()[0]
        field = ".".join(map(str, problem["loc"])) or "request"
        emit(events, correlation_id, "input_validation", "invalid_input", "refused", field)
        return {"request": None, "refusal": refuse("invalid_input", f"{field}: {problem['msg']}"), "events": events}
    needs = {"submit": "artifacts", "ask": "question"}.get(request["command"])
    if needs and needs not in request:
        emit(events, correlation_id, "input_validation", "invalid_input", "refused", needs)
        return {"request": None, "refusal": refuse("invalid_input", f"{request['command']} needs {needs}"), "events": events}
    return {"request": request, "refusal": None, "events": events}


def screen_texts(request: dict, cracked: dict[str, str], *, correlation_id: str) -> dict:
    """ stage 2: the Prompt Attacks filter on the analyst's question and every string cracked out of an artifact

        returns the texts that passed, prompt_attack_detected for EscalationSignals, the refusal when the question
        itself was attacked (an attacked artifact string is only withheld), and the events
    """

    events: list[GuardrailEvent] = []
    texts = {**({"analyst": request["question"]} if "question" in request else {}), **cracked}
    results = {source: screen(text) for source, text in texts.items() if text.strip()}
    attacked = [source for source, result in results.items() if prompt_attack_detected(result)]
    for source in attacked:
        emit(events, correlation_id, "prompt_attack", "prompt_attack", "refused" if source == "analyst" else "withheld", source)
    refusal = refuse("prompt_attack", "The question was blocked by the Prompt Attacks filter.") if "analyst" in attacked else None
    # what passed, as the guardrail returned it: its sensitive-information filter has masked any PII
    return {"texts": {source: results[source]["text"] if source in results else text
                      for source, text in texts.items() if source not in attacked},
            "prompt_attack_detected": bool(attacked), "refusal": refusal, "events": events}


def screen_review(request: ReviewRequest) -> ReviewRequest:
    """ a reviewer's free text (the edited narrative, the note, the reason) through the guardrail before it's stored """

    def guarded(text: str | None) -> str | None:
        return screen(text)["text"] if text and text.strip() else text

    edit = request.edit
    if edit is not None:
        edit = edit.model_copy(update={"narrative": guarded(edit.narrative), "note": guarded(edit.note)})
    return request.model_copy(update={"edit": edit, "reason": guarded(request.reason)})


def check_turn(raw: dict, *, incident: NormalizedIncident | None, cracked: dict[str, str], correlation_id: str) -> dict:
    """ stages 1 to 3; cracked maps each source (an artifact, or one of its fields) to the text cracked out of it

        returns the request, the route (None for submit), any refusal, why readiness stopped a classify turn,
        the screened texts, prompt_attack_detected for EscalationSignals, the R5 invocation, and the events
    """

    events: list[GuardrailEvent] = []
    turn = {"request": None, "route": "refuse", "refusal": None, "problems": [], "texts": {},
            "prompt_attack_detected": False, "rule_invocations": [], "events": events}

    # 1. input validation, before any model call
    validated = validate_request(raw, correlation_id=correlation_id)
    events += validated["events"]
    if validated["refusal"]:
        return {**turn, "refusal": validated["refusal"]}
    request = turn["request"] = validated["request"]

    # 2. the Prompt Attacks filter on the analyst's input and every string cracked out of an artifact
    screened = screen_texts(request, cracked, correlation_id=correlation_id)
    events += screened["events"]
    turn |= {"prompt_attack_detected": screened["prompt_attack_detected"], "texts": screened["texts"]}
    if screened["refusal"]:
        return {**turn, "refusal": screened["refusal"]}
    if "analyst" in screened["texts"]:
        # the rest of the turn sees the question as the guardrail returned it, never the raw input
        request = turn["request"] = {**request, "question": screened["texts"]["analyst"]}
    if request["command"] == "submit":
        # submit ingests; readiness is decided when the incident is analyzed
        return {**turn, "route": None}

    # 3. the readiness gate: the label, then the deterministic check regardless of the label
    label = classify(request["question"]) if request["command"] == "ask" else "classify"
    problems = [] if incident else ["there's no normalized record for this incident"]
    if incident:
        problems += [f"{field} is missing" for field in REQUIRED_FIELDS if getattr(incident, field) is None]
        r5 = confidence_floor(R5Inputs(confidences=incident.confidences))
        turn["rule_invocations"].append(create_invocation(incident.incident_id, r5))
        if r5.outcome != "ready":
            problems.append(f"R5 returned {r5.outcome} for {r5.missing_field}")

    route = ROUTES[label]
    if route == "run_workflow" and problems:
        route = "route_to_analyst"
        emit(events, correlation_id, "readiness", "not_ready", "routed_to_analyst", "; ".join(problems))
    turn |= {"route": route, "problems": problems}
    if label == "action":
        emit(events, correlation_id, "readiness", "action", "refused", request["question"][:80])
        turn["refusal"] = refuse("action_requested", "FieldSight only proposes; nothing is written without "
                                                     "a second person's approval in the review queue.")
    elif label == "out_of_scope":
        emit(events, correlation_id, "readiness", "out_of_scope", "refused", request["question"][:80])
        turn["refusal"] = refuse("out_of_scope", "That is outside OSHA recordkeeping, reporting and hazard control.")
    return turn
