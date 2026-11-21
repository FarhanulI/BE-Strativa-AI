"""Unit tests (no database) for AiBudgetService and AiUsageService (step 3c)."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

import app.ai_platform as ai_platform
from app.ai_platform import (
    AiBudgetService,
    AiCallContext,
    AiPlatformConfig,
    AiUsageService,
    budget_service,
    context,
    usage_service,
    usage_types,
)
from app.ai_platform.budget_service import (
    build_status,
    compute_percent_used,
    compute_state,
)
from app.core import FakeClock, ValidationFailed

LIMIT = 1_000


class _NoSession:
    """A sessionmaker that must never be used: validation happens before any read."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no session may be opened")


def _clock(year: int = 2026, month: int = 6, day: int = 15) -> FakeClock:
    return FakeClock(datetime(year, month, day, 12, 0, tzinfo=UTC))


def _workspace_ctx() -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=uuid4(), request_id="r")


# --- state rule (D-18) ---


@pytest.mark.parametrize(
    ("spent", "reserved", "expected"),
    [
        (0, 0, "ok"),
        (799, 0, "ok"),  # just below 80 percent
        (800, 0, "warning"),  # exactly 80 percent
        (801, 0, "warning"),
        (500, 499, "ok"),  # reservations alone never warn
        (0, 999, "ok"),  # one below the limit by reservation only
        (0, 1_000, "exhausted"),  # exactly at the limit via a reservation
        (900, 99, "warning"),  # spent + reserved one below the limit
        (900, 100, "exhausted"),  # exactly at the limit
        (1_000, 0, "exhausted"),
        (1_500, 0, "exhausted"),  # spent above the limit (overshoot on settlement)
    ],
)
def test_state_boundaries(spent: int, reserved: int, expected: str) -> None:
    assert compute_state(limit=LIMIT, spent=spent, reserved=reserved) == expected


def test_state_with_a_zero_limit_is_exhausted() -> None:
    assert compute_state(limit=0, spent=0, reserved=0) == "exhausted"


def test_state_uses_only_the_counters_and_the_limit() -> None:
    parameters = inspect.signature(compute_state).parameters
    assert set(parameters) == {"limit", "spent", "reserved"}


@pytest.mark.parametrize(
    ("limit", "spent", "expected"),
    [
        (1_000, 0, 0),
        (1_000, 9, 0),
        (1_000, 10, 1),
        (1_000, 799, 79),  # floor, not round
        (1_000, 800, 80),
        (1_000, 1_000, 100),
        (1_000, 2_500, 250),  # not capped: settled spend can overshoot
        (3, 1, 33),
        (0, 0, 100),  # spec gap: a zero limit reports 100
    ],
)
def test_percent_used_is_floored_on_settled_spend(limit: int, spent: int, expected: int) -> None:
    assert compute_percent_used(limit=limit, spent=spent) == expected


@pytest.mark.parametrize(
    ("spent", "reserved", "remaining"),
    [(0, 0, 1_000), (300, 200, 500), (600, 400, 0), (900, 400, 0), (2_000, 0, 0)],
)
def test_remaining_is_clamped_at_zero(spent: int, reserved: int, remaining: int) -> None:
    status = build_status(
        period_start=date(2026, 6, 1), limit=LIMIT, spent=spent, reserved=reserved
    )
    assert status.remaining_micro_usd == remaining
    assert status.currency == "USD"
    assert status.limit_micro_usd == LIMIT


def test_status_with_a_zero_limit() -> None:
    status = build_status(period_start=date(2026, 6, 1), limit=0, spent=0, reserved=0)
    assert (status.percent_used, status.state, status.remaining_micro_usd) == (100, "exhausted", 0)


# --- input validation ---


async def test_budget_status_refuses_a_system_context() -> None:
    service = AiBudgetService(_NoSession(), _clock(), AiPlatformConfig())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="workspace-scoped"):
        await service.get_status(AiCallContext.system(request_id="r"))


async def test_usage_refuses_a_system_context() -> None:
    service = AiUsageService(_NoSession(), _clock())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="workspace-scoped"):
        await service.get_workspace_usage(
            AiCallContext.system(request_id="r"), period_start=date(2026, 6, 1), group_by="task"
        )


@pytest.mark.parametrize("period", [date(2026, 6, 2), date(2026, 6, 30), date(2026, 5, 15)])
async def test_usage_requires_the_first_day_of_a_month(period: date) -> None:
    service = AiUsageService(_NoSession(), _clock())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="first day"):
        await service.get_workspace_usage(_workspace_ctx(), period_start=period, group_by="task")


async def test_usage_rejects_a_datetime_period() -> None:
    service = AiUsageService(_NoSession(), _clock())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="first day"):
        await service.get_workspace_usage(
            _workspace_ctx(),
            period_start=datetime(2026, 6, 1, tzinfo=UTC),  # type: ignore[arg-type]
            group_by="task",
        )


@pytest.mark.parametrize("period", [date(2026, 7, 1), date(2027, 1, 1), date(2030, 12, 1)])
async def test_usage_rejects_a_future_month(period: date) -> None:
    service = AiUsageService(_NoSession(), _clock(2026, 6, 30))  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        await service.get_workspace_usage(_workspace_ctx(), period_start=period, group_by="day")


async def test_usage_rejects_an_unknown_grouping() -> None:
    service = AiUsageService(_NoSession(), _clock())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="group_by"):
        await service.get_workspace_usage(
            _workspace_ctx(),
            period_start=date(2026, 6, 1),
            group_by="provider",  # type: ignore[arg-type]
        )


# --- reflection and exports ---


def _public_names(module: Any) -> list[str]:
    names = [name for name in dir(module) if not name.startswith("__")]
    for _, member in inspect.getmembers(module, inspect.isclass):
        if member.__module__ == module.__name__:
            names.extend(getattr(member, "model_fields", {}))
            names.extend(name for name in vars(member) if not name.startswith("__"))
    return names


@pytest.mark.parametrize("module", [context, usage_types, budget_service, usage_service])
def test_no_name_or_field_contains_the_word_token(module: Any) -> None:
    offenders = [name for name in _public_names(module) if "token" in name.lower()]
    assert offenders == []


def test_new_names_are_exported_and_the_old_ones_are_unchanged() -> None:
    previous = {
        "AiBudgetExceeded", "AiCapability", "AiContentRefused", "AiContextBlock", "AiErrorCode",
        "AiInputTooLarge", "AiModality", "AiModalityNotSupported", "AiNoRoute", "AiOutputInvalid",
        "AiPart", "AiPlatformConfig", "AiProviderNotConfigured", "AiProviderUnavailable",
        "AiTaskDefinition", "AiTaskName", "AiTaskNotReady", "AiTaskRegistry", "AiTaskRequest",
        "AudioPart", "CostClass", "EmbeddingLimits", "ImagePart", "LatencyClass", "MediaRef",
        "OutputSchemaRegistry", "QualityClass", "TaskScope", "TextPart", "VideoPart",
    }  # fmt: skip
    added = {
        "AiCallContext", "AiBudgetService", "AiUsageService", "AiBudgetStatus", "AiUsageReport",
        "AiUsageSummary", "FakeAiProvider", "ScriptedResponse", "AiTaskResult", "AiRequestStatus",
        "AiOrchestrator",
    }  # fmt: skip
    assert set(ai_platform.__all__) == previous | added
    assert len(ai_platform.__all__) == len(set(ai_platform.__all__))
    for name in added:
        assert hasattr(ai_platform, name)
    for internal in ("AiUsageGroup", "AiUsageTotals", "BudgetCoordinator"):
        assert internal not in ai_platform.__all__
