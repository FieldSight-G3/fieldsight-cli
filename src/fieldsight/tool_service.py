"""Read-only Gateway tools with a session-bound subject and per-call access checks."""

from __future__ import annotations

from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.errors import FieldSightError


class GetExtractionInput(BaseModel):
    """Read the extraction for the authenticated caller's bound session."""

    model_config = ConfigDict(extra="forbid")


class SimilarIncidentsInput(BaseModel):
    """Choose the number of candidates, never the subject incident."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=3, ge=1, le=5, description="Maximum number of similar incidents")


class SimilarCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: UUID
    outcome: dict[str, Any]
    deciding_rule: str
    similarity_score: float = Field(ge=0, le=1)
    matching_narrative_span: str


FailureCode = Literal["unauthenticated", "not_entitled", "not_found", "insufficient_data", "unavailable", "invalid_input"]


class ToolFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: FailureCode
    message: str


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any] | None = None
    error: ToolFailure | None = None


class ToolDenied(FieldSightError):
    def __init__(self, code: FailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class ReadStore(Protocol):
    def extraction(self, verified_email: str, thread_id: str) -> dict[str, Any]: ...
    def similar(self, verified_email: str, thread_id: str, limit: int) -> list[SimilarCandidate]: ...


class ToolService:
    def __init__(self, store: ReadStore) -> None:
        self.store = store

    def get_incident_extraction(self, verified_email: str, thread_id: str, payload: dict[str, Any]) -> ToolResponse:
        GetExtractionInput.model_validate(payload)
        result = self.store.extraction(verified_email, thread_id)
        return ToolResponse(ok=True, result=result)

    def find_similar_incidents(self, verified_email: str, thread_id: str, payload: dict[str, Any]) -> ToolResponse:
        arguments = SimilarIncidentsInput.model_validate(payload)
        items = self.store.similar(verified_email, thread_id, arguments.limit)
        return ToolResponse(ok=True, result={"items": [item.model_dump(mode="json") for item in items]})
