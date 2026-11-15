"""ai_platform domain events (spec 7), all v1, registered once in ``DEFAULT_EVENT_REGISTRY``.

Registration happens at import time of this module, like ``app.profile.events`` and
``app.workspace.events``. ``app.ai_platform`` imports this module so the registration is in place
whenever the package is imported. The classes are not exported from the package root (spec 5 lists
no event class there); import them from ``app.ai_platform.events``.

Payloads carry ids, codes, scope, period and integer amounts only (INV-18). No field name contains
``token`` or matches the envelope's sensitive-key patterns, and no field carries content.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal

from app.events_outbox import DEFAULT_EVENT_REGISTRY, DomainEvent


class AiRequestQueued(DomainEvent):
    event_type: ClassVar[str] = "ai.request_queued"
    task: str
    output_schema_name: str
    output_schema_version: int


class AiRequestCompleted(DomainEvent):
    event_type: ClassVar[str] = "ai.request_completed"
    task: str
    output_schema_name: str
    output_schema_version: int
    attempts: int
    input_units: int
    output_units: int
    cost_micro_usd: int


class AiRequestFailed(DomainEvent):
    event_type: ClassVar[str] = "ai.request_failed"
    task: str
    error_code: str
    attempts: int
    cost_micro_usd: int


class AiBudgetThresholdReached(DomainEvent):
    event_type: ClassVar[str] = "ai.budget_threshold_reached"
    scope: Literal["workspace", "system"]
    period_start: date
    threshold_percent: Literal[80] = 80
    limit_micro_usd: int
    spent_micro_usd: int
    reserved_micro_usd: int


class AiBudgetExhausted(DomainEvent):
    event_type: ClassVar[str] = "ai.budget_exhausted"
    scope: Literal["workspace", "system"]
    period_start: date
    threshold_percent: Literal[100] = 100
    limit_micro_usd: int
    spent_micro_usd: int
    reserved_micro_usd: int


AI_REQUEST_AGGREGATE = "ai_request"
AI_BUDGET_AGGREGATE = "ai_budget"

for event_model in (
    AiRequestQueued,
    AiRequestCompleted,
    AiRequestFailed,
    AiBudgetThresholdReached,
    AiBudgetExhausted,
):
    DEFAULT_EVENT_REGISTRY.register(event_model)
