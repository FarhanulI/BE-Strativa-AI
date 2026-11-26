"""Result types of the orchestrator (spec 5.2).

Frozen, ``extra="forbid"``. Neither type has a provider or model field (INV-2): ``routing_id`` is
an opaque usage-record id. ``AiRequestStatus`` deliberately has no output field: the domain module
that owns the schema reads it through ``get_output``.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai_platform.enums import AiTaskName
from app.ai_platform.usage_types import AiUsageSummary

_FROZEN = ConfigDict(frozen=True, extra="forbid")

RequestStatusName = Literal["queued", "running", "succeeded", "failed"]


class AiTaskResult(BaseModel):
    model_config = _FROZEN

    request_id: UUID
    task: AiTaskName
    output: BaseModel  # validated instance of the registered output schema
    output_schema_name: str
    output_schema_version: int = Field(ge=1)
    usage: AiUsageSummary
    routing_id: UUID  # opaque; the final usage record id. Never a provider or model name.

    @field_validator("output", mode="before")
    @classmethod
    def _output_is_a_validated_instance(cls, value: Any) -> Any:
        # A plain mapping would otherwise be coerced into an empty BaseModel and lose its data.
        if not isinstance(value, BaseModel):
            raise ValueError("output must be a validated model instance")
        return value


class AiRequestStatus(BaseModel):
    model_config = _FROZEN

    request_id: UUID
    task: AiTaskName
    status: RequestStatusName
    error_code: str | None
    usage: AiUsageSummary
