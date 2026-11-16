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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_platform.catalog import CatalogModel, ModelCatalog
from app.ai_platform.enums import AiCapability, AiModality, LatencyClass, QualityClass
from app.ai_platform.errors import (
    AiBudgetExceeded,
    AiInputTooLarge,
    AiModalityNotSupported,
    AiNoRoute,
    AiProviderNotConfigured,
)
from app.ai_platform.pricing import estimate_embedding_micro_usd, estimate_generation_micro_usd
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


def _failure_for(emptied_at: int, modality_rejected: bool) -> RoutingFailure:
    """The step at which the candidate list became empty decides the failure (10.2 step 10)."""
    if emptied_at == 1:
        if modality_rejected:
            return RoutingFailure.MODALITY_NOT_SUPPORTED
        return RoutingFailure.NO_ROUTE
    if emptied_at == 2:
        return RoutingFailure.PROVIDER_NOT_CONFIGURED
    if emptied_at == 3:
        return RoutingFailure.INPUT_TOO_LARGE
    if emptied_at == 7:
        return RoutingFailure.BUDGET_EXCEEDED
    return RoutingFailure.NO_ROUTE


def _input_with_margin(units: int, margin_percent: int) -> int:
    """``ceil(units * (100 + margin) / 100)`` in integer arithmetic."""
    return -(-(units * (100 + margin_percent)) // 100)


def route(routing_input: RoutingInput) -> RoutingResult:
    """Select and order candidate models (spec 10.2, steps 1 to 10). Pure and deterministic."""
    task = routing_input.task
    is_embedding = routing_input.max_output_units is None
    padded_input = _input_with_margin(
        routing_input.estimated_input_units, routing_input.context_safety_margin_percent
    )
    required_quality = task.quality
    if (
        routing_input.quality_floor is not None
        and routing_input.quality_floor.rank > required_quality.rank
    ):
        required_quality = routing_input.quality_floor
    pinned = routing_input.pinned

    # Sorting up front makes the outcome independent of the catalog's model order (INV-5).
    considered = sorted(
        (
            entry
            for entry in routing_input.catalog.models()
            if pinned is None or (entry.provider, entry.model) == pinned
        ),
        key=lambda entry: (entry.provider, entry.model),
    )

    def output_units(entry: CatalogModel) -> int:
        if routing_input.max_output_units is None:
            return 0
        if entry.max_output_units is None:
            return routing_input.max_output_units
        return min(routing_input.max_output_units, entry.max_output_units)

    costs: dict[tuple[str, str], int] = {}

    def cost_of(entry: CatalogModel) -> int:
        key = (entry.provider, entry.model)
        if key not in costs:
            if is_embedding:
                costs[key] = estimate_embedding_micro_usd(padded_input, entry)
            else:
                costs[key] = estimate_generation_micro_usd(padded_input, output_units(entry), entry)
        return costs[key]

    def step_capability_modality(entry: CatalogModel) -> ReasonCode | None:
        if not entry.enabled:
            return ReasonCode.DISABLED
        if not task.capabilities <= entry.capabilities:
            return ReasonCode.CAPABILITY
        if (
            not routing_input.input_modalities_present <= entry.input_modalities
            or not task.output_modalities <= entry.output_modalities
        ):
            return ReasonCode.MODALITY
        return None

    def step_configured(entry: CatalogModel) -> ReasonCode | None:
        if routing_input.provider_configured.get(entry.provider, False):
            return None
        return ReasonCode.NOT_CONFIGURED

    def step_context(entry: CatalogModel) -> ReasonCode | None:
        if padded_input + output_units(entry) <= entry.context_window_units:
            return None
        return ReasonCode.CONTEXT

    def step_quality(entry: CatalogModel) -> ReasonCode | None:
        if entry.quality_tier >= required_quality:
            return None
        return ReasonCode.QUALITY

    def step_cost_class(entry: CatalogModel) -> ReasonCode | None:
        if cost_of(entry) <= routing_input.cost_ceiling_micro_usd:
            return None
        return ReasonCode.COST_CLASS

    def step_available(entry: CatalogModel) -> ReasonCode | None:
        if (entry.provider, entry.model) in routing_input.unavailable_models:
            return ReasonCode.UNAVAILABLE
        return None

    def step_budget(entry: CatalogModel) -> ReasonCode | None:
        if cost_of(entry) <= routing_input.remaining_budget_micro_usd:
            return None
        return ReasonCode.BUDGET

    steps: tuple[tuple[int, Callable[[CatalogModel], ReasonCode | None]], ...] = (
        (1, step_capability_modality),
        (2, step_configured),
        (3, step_context),
        (4, step_quality),
        (5, step_cost_class),
        (6, step_available),
        (7, step_budget),
    )

    rejected: dict[tuple[str, str], ReasonCode] = {}
    alive = considered
    emptied_at: int | None = None if considered else 1
    modality_rejected = False
    for number, check in steps:
        if not alive:
            break
        survivors: list[CatalogModel] = []
        for entry in alive:
            reason = check(entry)
            if reason is None:
                survivors.append(entry)
                continue
            rejected[(entry.provider, entry.model)] = reason
            if reason is ReasonCode.MODALITY:
                modality_rejected = True
        alive = survivors
        if not alive and emptied_at is None:
            emptied_at = number

    billing: dict[tuple[str, str], BillingMode] = {}
    for entry in alive:
        mode = routing_input.provider_billing_mode.get(entry.provider)
        if mode is None:
            raise ValueError("billing mode is missing for a candidate provider")
        billing[(entry.provider, entry.model)] = mode

    # Step 8: rank. Model, then provider, are the final tie-breaks so ties are deterministic.
    latency = task.latency

    def rank_key(entry: CatalogModel) -> tuple[int | str, ...]:
        if latency is LatencyClass.INTERACTIVE:
            return (entry.latency_p50_ms, cost_of(entry), entry.model, entry.provider)
        if latency is LatencyClass.STANDARD:
            return (cost_of(entry), entry.latency_p50_ms, entry.model, entry.provider)
        return (cost_of(entry), entry.model, entry.provider)

    ranked = sorted(alive, key=rank_key)

    # Step 9: billing-mode lock to the first-ranked candidate's mode.
    selected: list[CatalogModel] = []
    if ranked:
        locked_mode = billing[(ranked[0].provider, ranked[0].model)]
        for entry in ranked:
            key = (entry.provider, entry.model)
            if billing[key] == locked_mode:
                selected.append(entry)
            else:
                rejected[key] = ReasonCode.BILLING_MODE

    candidates = tuple(
        RoutedModel(
            provider=entry.provider,
            model=entry.model,
            billing_mode=billing[(entry.provider, entry.model)],
            estimated_cost_micro_usd=cost_of(entry),
            route_rank=position,
        )
        for position, entry in enumerate(selected, start=1)
    )

    # Snapshot order: eligible candidates in rank order, then the rest by (provider, model).
    decisions = [
        CandidateDecision(
            provider=routed.provider,
            model=routed.model,
            eligible=True,
            reason_code=None,
            billing_mode=routed.billing_mode,
            estimated_cost_micro_usd=routed.estimated_cost_micro_usd,
            route_rank=routed.route_rank,
        )
        for routed in candidates
    ]
    for entry in considered:
        key = (entry.provider, entry.model)
        if key in rejected:
            decisions.append(
                CandidateDecision(
                    provider=entry.provider,
                    model=entry.model,
                    eligible=False,
                    reason_code=rejected[key].value,
                    billing_mode=billing.get(key),
                    estimated_cost_micro_usd=costs.get(key),
                    route_rank=None,
                )
            )

    snapshot = tuple(
        MappingProxyType(
            {
                "provider": decision.provider,
                "model": decision.model,
                "eligible": decision.eligible,
                "reason_code": decision.reason_code,
            }
        )
        for decision in decisions
    )
    failure = None
    if not candidates:
        failure = _failure_for(emptied_at if emptied_at is not None else 1, modality_rejected)
    return RoutingResult(
        candidates=candidates,
        snapshot=snapshot,
        failure=failure,
        routing_version=routing_input.routing_version,
    )
