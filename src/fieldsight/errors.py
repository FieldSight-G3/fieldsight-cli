""" FieldSight's own exceptions, so extraction, retrieval, rules, and gate failures can be told apart by type """

from typing import Literal

FailureCode = Literal["unauthenticated", "not_entitled", "not_found", "insufficient_data", "unavailable", "invalid_input"]


class FieldSightError(Exception):
    """ base class for every error FieldSight raises on purpose """


class ExtractionError(FieldSightError):
    """ Textract couldn't crack an artifact or corpus doc """


class IndexingError(FieldSightError):
    """ the corpus couldn't be written to, or synced into, the Knowledge Base """


class RetrievalError(FieldSightError):
    """ the corpus Knowledge Base couldn't be searched, so nothing can be grounded """


class RuleError(FieldSightError):
    """ a rule couldn't run, e.g. the rule whose decision it uses hasn't run yet """


class GuardrailError(FieldSightError):
    """ Bedrock Guardrails couldn't screen a string, so it can't be let through """

class PlanError(FieldSightError):
    """ the Coordinator returned no valid dispatch plan, even after a retry """

class ToolDenied(FieldSightError):
    """ a Gateway read tool refused the call; code maps to the HTTP status """

    def __init__(self, code: FailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)
