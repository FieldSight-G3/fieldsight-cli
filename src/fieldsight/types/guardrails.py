""" shapes the guardrail pipeline passes around: plain dicts, validated at the boundary """

from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import ConfigDict, Field, StringConstraints, TypeAdapter, with_config

MAX_QUESTION_CHARS = 2000
MAX_ARTIFACTS = 20
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
# what the packets hold: forms and notes as PDF or text, photos as JPEG or PNG
ARTIFACT_NAME = r"(?i)^[^/\\]+\.(pdf|txt|jpe?g|png)$"


@with_config(ConfigDict(extra="forbid"))
class Artifact(TypedDict):
    """ one uploaded artifact, checked before it is stored or cracked """

    name: Annotated[str, StringConstraints(pattern=ARTIFACT_NAME)]
    size_bytes: Annotated[int, Field(gt=0, le=MAX_ARTIFACT_BYTES)]


@with_config(ConfigDict(extra="forbid"))
class TurnRequest(TypedDict):
    """ what the analyst sent: submit carries artifacts, ask carries a question, analyze carries neither """

    command: Literal["submit", "analyze", "ask"]
    incident_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    question: NotRequired[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)]]
    artifacts: NotRequired[Annotated[list[Artifact], Field(min_length=1, max_length=MAX_ARTIFACTS)]]


Stage = Literal["input_validation", "prompt_attack", "readiness", "output"]
Remedy = Literal["refused", "withheld", "routed_to_analyst", "regenerated", "rule_run", "redacted", "appended", "gate_miss", "blocked"]


class GuardrailEvent(TypedDict):
    """ one guardrail failure and what was done about it; never silently repaired """

    correlation_id: str
    stage: Stage
    failure: str        # what failed, e.g. prompt_attack, uncited_claim
    remedy: Remedy
    trigger: str        # the field, source, rule or claim that set it off; never PII


# distinct from retrieval's RefusalReason, which covers why a corpus search couldn't ground an answer
GuardrailRefusal = Literal["invalid_input", "prompt_attack", "action_requested", "out_of_scope", "output_blocked", "bound_reached"]


class Refusal(TypedDict):
    """ a refusal is an answer, not an error: the reason code, what to tell the analyst, and where to escalate """

    reason: GuardrailRefusal
    message: str
    escalation: str


# what each readiness label leads to; route_to_analyst is the deterministic override
Route = Literal["answer_from_retrieval", "run_workflow", "route_to_analyst", "refuse"]


TURN_REQUEST = TypeAdapter(TurnRequest)
