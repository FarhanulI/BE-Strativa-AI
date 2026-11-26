"""AC-6: the ai.* event models (spec 7). No database."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ai_platform import events
from app.ai_platform.events import (
    AiBudgetExhausted,
    AiBudgetThresholdReached,
    AiRequestCompleted,
    AiRequestFailed,
    AiRequestQueued,
)
from app.events_outbox import DEFAULT_EVENT_REGISTRY, DomainEvent, OutboxEvent, publish
from app.events_outbox.contracts import _SENSITIVE_KEY

ALL_EVENTS: dict[str, type[DomainEvent]] = {
    "ai.request_queued": AiRequestQueued,
    "ai.request_completed": AiRequestCompleted,
    "ai.request_failed": AiRequestFailed,
    "ai.budget_threshold_reached": AiBudgetThresholdReached,
    "ai.budget_exhausted": AiBudgetExhausted,
}
BASE_FIELDS = set(DomainEvent.model_fields)


def _kwargs(event_type: str) -> dict[str, Any]:
    base: dict[str, Any] = {"aggregate_id": uuid4(), "occurred_at": datetime.now(UTC)}
    if event_type == "ai.request_queued":
        return base | {
            "aggregate_type": "ai_request",
            "task": "GENERATE_HOOK_VARIATIONS",
            "output_schema_name": "HookVariationSet",
            "output_schema_version": 1,
        }
    if event_type == "ai.request_completed":
        return base | {
            "aggregate_type": "ai_request",
            "task": "GENERATE_HOOK_VARIATIONS",
            "output_schema_name": "HookVariationSet",
            "output_schema_version": 1,
            "attempts": 2,
            "input_units": 10,
            "output_units": 20,
            "cost_micro_usd": 30,
        }
    if event_type == "ai.request_failed":
        return base | {
            "aggregate_type": "ai_request",
            "task": "GENERATE_HOOK_VARIATIONS",
            "error_code": "output_invalid",
            "attempts": 3,
            "cost_micro_usd": 5,
        }
    return base | {
        "aggregate_type": "ai_budget",
        "scope": "system",
        "period_start": date(2030, 1, 1),
        "limit_micro_usd": 100,
        "spent_micro_usd": 80,
        "reserved_micro_usd": 10,
    }


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, row: Any) -> None:
        self.added.append(row)


def _registered_for(model: type[DomainEvent]) -> list[tuple[str, int]]:
    return [
        key
        for key, registered in DEFAULT_EVENT_REGISTRY._event_types.items()  # noqa: SLF001
        if registered is model
    ]


@pytest.mark.parametrize("event_type", sorted(ALL_EVENTS))
def test_registered_exactly_once_as_v1(event_type: str) -> None:
    model = ALL_EVENTS[event_type]
    assert model.event_type == event_type
    assert model.event_version == 1
    assert _registered_for(model) == [(event_type, 1)]


def test_registry_has_no_other_ai_events() -> None:
    ai_keys = {
        key for key in DEFAULT_EVENT_REGISTRY._event_types if key[0].startswith("ai.")  # noqa: SLF001
    }
    assert ai_keys == {(event_type, 1) for event_type in ALL_EVENTS}


def test_registering_again_is_rejected() -> None:
    with pytest.raises(ValueError, match="already registered"):
        DEFAULT_EVENT_REGISTRY.register(AiBudgetExhausted)


def test_events_module_is_imported_by_the_package_root() -> None:
    import app.ai_platform as package

    assert package._events is events  # noqa: SLF001
    for name in ("AiBudgetExhausted", "AiBudgetThresholdReached", "AiRequestQueued"):
        assert not hasattr(package, name)  # importable from app.ai_platform.events only


@pytest.mark.parametrize("event_type", sorted(ALL_EVENTS))
def test_extra_fields_are_forbidden(event_type: str) -> None:
    with pytest.raises(ValidationError):
        ALL_EVENTS[event_type](**_kwargs(event_type), surprise="x")


@pytest.mark.parametrize("event_type", sorted(ALL_EVENTS))
def test_payload_field_names_are_safe(event_type: str) -> None:
    model = ALL_EVENTS[event_type]
    for name in set(model.model_fields) - BASE_FIELDS:
        assert "token" not in name.lower()
        assert not _SENSITIVE_KEY.search(name), name
        assert not re.search(r"prompt|completion|content|text|output$|key|url", name), name


EXPECTED_PAYLOAD = {
    "ai.request_queued": {"task", "output_schema_name", "output_schema_version"},
    "ai.request_completed": {
        "task",
        "output_schema_name",
        "output_schema_version",
        "attempts",
        "input_units",
        "output_units",
        "cost_micro_usd",
    },
    "ai.request_failed": {"task", "error_code", "attempts", "cost_micro_usd"},
    "ai.budget_threshold_reached": {
        "scope",
        "period_start",
        "threshold_percent",
        "limit_micro_usd",
        "spent_micro_usd",
        "reserved_micro_usd",
    },
    "ai.budget_exhausted": {
        "scope",
        "period_start",
        "threshold_percent",
        "limit_micro_usd",
        "spent_micro_usd",
        "reserved_micro_usd",
    },
}


@pytest.mark.parametrize("event_type", sorted(ALL_EVENTS))
def test_payload_matches_the_spec_table(event_type: str) -> None:
    event = ALL_EVENTS[event_type](**_kwargs(event_type))
    assert set(event.envelope().payload) == EXPECTED_PAYLOAD[event_type]


def test_threshold_percent_is_fixed() -> None:
    threshold = AiBudgetThresholdReached(**_kwargs("ai.budget_threshold_reached"))
    exhausted = AiBudgetExhausted(**_kwargs("ai.budget_exhausted"))
    assert threshold.threshold_percent == 80
    assert exhausted.threshold_percent == 100
    with pytest.raises(ValidationError):
        AiBudgetThresholdReached(**_kwargs("ai.budget_threshold_reached"), threshold_percent=100)
    bad = {**_kwargs("ai.budget_threshold_reached"), "threshold_percent": 90}
    with pytest.raises(ValidationError):
        AiBudgetThresholdReached(**bad)
    with pytest.raises(ValidationError):
        AiBudgetExhausted(**{**_kwargs("ai.budget_exhausted"), "threshold_percent": 80})


def test_scope_is_restricted() -> None:
    with pytest.raises(ValidationError):
        AiBudgetExhausted(**{**_kwargs("ai.budget_exhausted"), "scope": "global"})


@pytest.mark.parametrize("event_type", sorted(ALL_EVENTS))
async def test_publish_accepts_each_event(event_type: str) -> None:
    session = _FakeSession()
    workspace_id = uuid4()
    event = ALL_EVENTS[event_type](**_kwargs(event_type), workspace_id=workspace_id)
    row = await publish(session, event)  # type: ignore[arg-type]
    assert session.added == [row]
    assert isinstance(row, OutboxEvent)
    assert row.event_type == event_type
    assert row.event_version == 1
    assert row.workspace_id == workspace_id
    assert set(row.payload) == EXPECTED_PAYLOAD[event_type]


async def test_system_scope_event_has_no_workspace() -> None:
    session = _FakeSession()
    event = AiBudgetExhausted(**_kwargs("ai.budget_exhausted"))
    row = await publish(session, event)  # type: ignore[arg-type]
    assert row.workspace_id is None
