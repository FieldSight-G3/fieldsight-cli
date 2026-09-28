"""Read-only Gateway tools with a session-bound subject and per-call access checks."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.errors import FailureCode
from fieldsight.schemas.incidents import SimilarCandidate


class GetExtractionInput(BaseModel):
    """Read the extraction for the authenticated caller's bound session."""

    model_config = ConfigDict(extra="forbid")


class SimilarIncidentsInput(BaseModel):
    """Choose the number of candidates, never the subject incident."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=3, ge=1, le=5, description="Maximum number of similar incidents")


class ToolFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: FailureCode
    message: str


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: dict[str, Any] | None = None
    error: ToolFailure | None = None


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
