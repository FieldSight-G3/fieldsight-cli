"""The Gateway read tools' inputs and their structured response; the OpenAPI contract is generated from these."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from fieldsight.errors import FailureCode


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
