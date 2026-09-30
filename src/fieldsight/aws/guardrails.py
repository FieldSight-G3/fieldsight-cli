""" Bedrock Guardrails outside a model call: screen a string with the ApplyGuardrail API """

from ..config import settings
from ..errors import GuardrailError
from . import clients
from .errors import raises


@raises(GuardrailError, "Bedrock Guardrails couldn't screen the text")
def screen(text: str, source: str = "INPUT") -> dict:
    """ run the guardrail over text without invoking a model

        source is INPUT for analyst input and strings cracked out of an artifact, OUTPUT for a model's reply
    """

    response = clients.guardrail_client().apply_guardrail(
        guardrailIdentifier=settings.bedrock_guardrail_id,
        guardrailVersion=settings.bedrock_guardrail_version,
        source=source,
        content=[{"text": {"text": text}}],
    )

    outputs = response.get("outputs", [])
    return {
        "action": response.get("action"),                   # NONE | GUARDRAIL_INTERVENED
        "text": outputs[0]["text"] if outputs else text,    # the guardrail's replacement text, when it intervened
        "assessments": response.get("assessments", []),     # which filters fired
    }


def prompt_attack_detected(result: dict) -> bool:
    """ whether the Prompt Attacks filter blocked the text, as opposed to any other filter """

    return any(
        found.get("type") == "PROMPT_ATTACK" and found.get("action") == "BLOCKED"
        for assessment in result["assessments"]
        for found in assessment.get("contentPolicy", {}).get("filters", [])
    )
