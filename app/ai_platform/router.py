"""The AI Router: a pure, deterministic selection function (spec 10, INV-5).

Internal to ai_platform (spec 5.6): not exported from the package root. The Router performs no
I/O, reads no clock, no environment and no randomness, and keeps no state (INV-1, INV-3, INV-5,
INV-22). Everything it needs arrives in a ``RoutingInput``: the circuit breaker, the budget
snapshot and the provider configuration are read by the caller. It never raises a domain error:
a failure is returned as a ``RoutingFailure`` and ``routing_error_class`` maps it to the error
class of ``errors.py`` for the caller to raise.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.enums import AiCapability, AiModality, QualityClass
from app.ai_platform.errors import (
    AiBudgetExceeded,
    AiInputTooLarge,
    AiModalityNotSupported,
    AiNoRoute,
    AiProviderNotConfigured,
)
from app.ai_platform.tasks import AiTaskDefinition

BillingMode = Literal["free_tier", "paid"]


class ReasonCode(StrEnum):
    """Why a model was not eligible (spec 10.2). The first failing step wins."""

    DISABLED = "disabled"
    CAPABILITY = "capability"
    MODALITY = "modality"
    NOT_CONFIGURED = "not_configured"
    CONTEXT = "context"
    QUALITY = "quality"
    COST_CLASS = "cost_class"
    UNAVAILABLE = "unavailable"
    BUDGET = "budget"
    BILLING_MODE = "billing_mode"


class RoutingFailure(StrEnum):
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    INPUT_TOO_LARGE = "input_too_large"
    BUDGET_EXCEEDED = "budget_exceeded"
    MODALITY_NOT_SUPPORTED = "modality_not_supported"
    NO_ROUTE = "no_route"


def routing_error_class(failure: RoutingFailure) -> type[Exception]:
    """The error class of ``errors.py`` for a failure. Returns the class; never raises it."""
    match failure:
        case RoutingFailure.PROVIDER_NOT_CONFIGURED:
            return AiProviderNotConfigured
        case RoutingFailure.INPUT_TOO_LARGE:
            return AiInputTooLarge
        case RoutingFailure.BUDGET_EXCEEDED:
            return AiBudgetExceeded
        case RoutingFailure.MODALITY_NOT_SUPPORTED:
            return AiModalityNotSupported
        case RoutingFailure.NO_ROUTE:
            return AiNoRoute


_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)


class RoutingInput(BaseModel):
    """Everything the Router reads. Validated on construction; invalid input is a ValueError
    (pydantic's ``ValidationError`` is a ``ValueError``)."""

    model_config = _STRICT

    task: AiTaskDefinition
    input_modalities_present: frozenset[AiModality]
    estimated_input_units: int = Field(ge=0)
    context_safety_margin_percent: int = Field(ge=0, le=99)
    # Already resolved by the caller (request value, task default, model maximum). The Router
    # additionally clamps it to each model's own maximum. None only for embedding tasks.
    max_output_units: int | None = Field(ge=1)
    quality_floor: QualityClass | None
    cost_ceiling_micro_usd: int = Field(ge=0)
    remaining_budget_micro_usd: int = Field(ge=0)
    provider_configured: Mapping[str, bool]
    provider_billing_mode: Mapping[str, BillingMode]
    unavailable_models: frozenset[tuple[str, str]]
    pinned: tuple[str, str] | None = None
    routing_version: str = Field(min_length=1)
    catalog: ModelCatalog

    @field_validator("provider_configured", "provider_billing_mode", mode="after")
    @classmethod
    def _freeze_mapping(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return MappingProxyType(dict(value))

    @field_validator("routing_version", mode="after")
    @classmethod
    def _version_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("routing_version must not be blank")
        return value

    @field_validator("input_modalities_present", mode="after")
    @classmethod
    def _modalities_not_empty(cls, value: frozenset[AiModality]) -> frozenset[AiModality]:
        if not value:
            raise ValueError("at least one input modality must be present")
        return value

    @field_validator("pinned", mode="after")
    @classmethod
    def _pinned_not_blank(cls, value: tuple[str, str] | None) -> tuple[str, str] | None:
        if value is not None and not all(part.strip() for part in value):
            raise ValueError("pinned must name a provider and a model")
        return value

    @model_validator(mode="after")
    def _output_units_match_task(self) -> RoutingInput:
        is_embedding = AiCapability.EMBEDDING in self.task.capabilities
        if is_embedding and self.max_output_units is not None:
            raise ValueError("max_output_units must be None for an embedding task")
        if not is_embedding and self.max_output_units is None:
            raise ValueError("max_output_units is required for a generation task")
        return self


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    """The outcome for one considered model. ``route_rank`` is set only for selected models."""

    provider: str
    model: str
    eligible: bool
    reason_code: str | None
    billing_mode: BillingMode | None
    estimated_cost_micro_usd: int | None
    route_rank: int | None


@dataclass(frozen=True, slots=True)
class RoutedModel:
    """A selected model, in rank order. ``route_rank`` starts at 1."""

    provider: str
    model: str
    billing_mode: BillingMode
    estimated_cost_micro_usd: int
    route_rank: int


@dataclass(frozen=True, slots=True)
class RoutingResult:
    candidates: tuple[RoutedModel, ...]
    # Every considered model, ids and codes only: {provider, model, eligible, reason_code}.
    snapshot: tuple[Mapping[str, str | bool | None], ...]
    failure: RoutingFailure | None
    routing_version: str

    def __post_init__(self) -> None:
        if bool(self.candidates) == (self.failure is not None):
            raise ValueError("failure is set exactly when there are no candidates")

    def snapshot_json(self) -> str:
        """Canonical, byte-stable JSON of the snapshot (sorted keys, no extra whitespace)."""
        return json.dumps(
            [dict(entry) for entry in self.snapshot],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
