"""Unit tests for the budget repository that need no database.

Every function must reject bad input with ValueError BEFORE it touches the session. The session
passed here is a bare object: any use of it raises AttributeError, which would fail the test.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest

from app.ai_platform import budget_repository as repo
from app.core import FakeClock, new_uuid7

NOW = FakeClock(datetime(2026, 11, 3, 12, 0, tzinfo=UTC)).now()
PERIOD = date(2026, 11, 1)
WS = new_uuid7(NOW)
ROW = new_uuid7(NOW)
REC = new_uuid7(NOW)
SESSION: Any = object()

BAD_MONEY: list[Any] = [-1, True, False, 1.0, "5", None, 2**63]


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def test_period_start_month_boundaries() -> None:
    assert repo.period_start_for(_utc(2026, 11, 1, 0, 0, 0)) == date(2026, 11, 1)
    assert repo.period_start_for(_utc(2026, 11, 30, 23, 59, 59)) == date(2026, 11, 1)
    assert repo.period_start_for(_utc(2026, 12, 1, 0, 0, 0)) == date(2026, 12, 1)


def test_period_start_december_to_january() -> None:
    assert repo.period_start_for(_utc(2026, 12, 31, 23, 59, 59)) == date(2026, 12, 1)
    assert repo.period_start_for(_utc(2027, 1, 1, 0, 0, 0)) == date(2027, 1, 1)


def test_period_start_converts_to_utc_before_taking_the_month() -> None:
    plus_five = timezone(timedelta(hours=5))
    minus_five = timezone(timedelta(hours=-5))
    # 2026-12-01 02:00 at +05:00 is still 2026-11-30 21:00 UTC.
    assert repo.period_start_for(datetime(2026, 12, 1, 2, 0, tzinfo=plus_five)) == date(2026, 11, 1)
    # 2026-11-30 21:00 at -05:00 is already 2026-12-01 02:00 UTC.
    assert repo.period_start_for(datetime(2026, 11, 30, 21, 0, tzinfo=minus_five)) == date(
        2026, 12, 1
    )


def test_period_start_rejects_naive_and_non_datetime() -> None:
    with pytest.raises(ValueError):
        repo.period_start_for(datetime(2026, 11, 3, 12, 0))
    with pytest.raises(ValueError):
        repo.period_start_for(date(2026, 11, 3))  # type: ignore[arg-type]


def _record(**overrides: Any) -> repo.ReservedUsageRecord:
    fields: dict[str, Any] = {
        "request_id": new_uuid7(NOW),
        "attempt_no": 1,
        "scope": "workspace",
        "workspace_id": WS,
        "task": "GENERATE_HOOK_VARIATIONS",
        "call_kind": "generation",
        "provider": "fakeprov",
        "model": "fake-chat-zq1",
        "catalog_version": "test-1",
        "price_version": "test-prices-1",
        "billing_mode": "paid",
        "routing_version": "r1",
        "route_rank": 1,
        "candidate_snapshot": [{"model": "fake-chat-zq1", "eligible": True, "reason_code": None}],
        "reserved_micro_usd": 100,
        "period_start": PERIOD,
        "started_at": NOW,
    }
    fields.update(overrides)
    return repo.ReservedUsageRecord(**fields)


def _settle_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "record_id": REC,
        "outcome": "succeeded",
        "input_units": 10,
        "output_units": 20,
        "cost_micro_usd": 5,
        "error_code": None,
        "finish_reason": "stop",
        "schema_valid": True,
        "validation_error_count": 0,
        "validation_error_types": [],
        "latency_ms": 120,
        "now": NOW,
    }
    args.update(overrides)
    return args


def _settle_full_args(**overrides: Any) -> dict[str, Any]:
    args = _settle_args()
    args.update(budget_row_id=ROW, reserved_estimate_micro_usd=5, limit_micro_usd=1000)
    args.update(overrides)
    return args


Call = Callable[[], Awaitable[Any]]


def _ensure(**kw: Any) -> Call:
    args: dict[str, Any] = {
        "scope": "workspace",
        "workspace_id": WS,
        "period_start": PERIOD,
        "limit_micro_usd": 1000,
        "now": NOW,
    }
    args.update(kw)
    return lambda: repo.ensure_budget_row(SESSION, **args)


@pytest.mark.parametrize("bad", BAD_MONEY)
async def test_ensure_budget_row_rejects_bad_limit(bad: Any) -> None:
    with pytest.raises(ValueError):
        await _ensure(limit_micro_usd=bad)()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"scope": "workspace", "workspace_id": None},
        {"scope": "system", "workspace_id": WS},
        {"scope": "tenant", "workspace_id": WS},
        {"scope": "workspace", "workspace_id": str(WS)},
        {"period_start": date(2026, 11, 2)},
        {"period_start": datetime(2026, 11, 1, tzinfo=UTC)},
        {"now": datetime(2026, 11, 3, 12, 0)},
    ],
)
async def test_ensure_budget_row_rejects_invalid_combinations(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await _ensure(**kwargs)()


@pytest.mark.parametrize("bad", BAD_MONEY)
async def test_reserve_rejects_bad_money(bad: Any) -> None:
    with pytest.raises(ValueError):
        await repo.reserve(SESSION, ROW, bad, 1000, NOW)
    with pytest.raises(ValueError):
        await repo.reserve(SESSION, ROW, 10, bad, NOW)


async def test_reserve_rejects_naive_time_and_bad_id() -> None:
    with pytest.raises(ValueError):
        await repo.reserve(SESSION, ROW, 10, 1000, datetime(2026, 11, 3))
    with pytest.raises(ValueError):
        await repo.reserve(SESSION, "not-a-uuid", 10, 1000, NOW)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", BAD_MONEY)
async def test_record_refusal_rejects_bad_limit(bad: Any) -> None:
    with pytest.raises(ValueError):
        await repo.record_refusal(SESSION, ROW, bad, NOW)


async def test_record_refusal_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        await repo.record_refusal(SESSION, ROW, 1000, datetime(2026, 11, 3))


@pytest.mark.parametrize("bad", BAD_MONEY)
async def test_insert_reserved_rejects_bad_reserved_amount(bad: Any) -> None:
    with pytest.raises(ValueError):
        await repo.insert_reserved_usage_record(SESSION, _record(reserved_micro_usd=bad))


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope": "workspace", "workspace_id": None},
        {"scope": "system", "workspace_id": WS},
        {"scope": "other"},
        {"attempt_no": 0},
        {"attempt_no": True},
        {"route_rank": 0},
        {"call_kind": "chat"},
        {"billing_mode": "free"},
        {"task": ""},
        {"started_at": datetime(2026, 11, 3, 12, 0)},
        {"period_start": date(2026, 10, 1)},  # not the UTC month of started_at
        {"candidate_snapshot": "text"},
        {"candidate_snapshot": [{"model": "m", "prompt": "free text"}]},
        {"candidate_snapshot": [{"model": {"nested": 1}}]},
        {"candidate_snapshot": ["m"]},
        {"request_id": "abc"},
    ],
)
async def test_insert_reserved_rejects_invalid_fields(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await repo.insert_reserved_usage_record(SESSION, _record(**overrides))


def test_reserved_record_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _record().reserved_micro_usd = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": "reserved"},
        {"outcome": "abandoned"},
        {"input_units": -1},
        {"input_units": True},
        {"output_units": 1.5},
        {"cost_micro_usd": -1},
        {"cost_micro_usd": True},
        {"cost_micro_usd": "1"},
        {"latency_ms": -1},
        {"validation_error_count": -1},
        {"schema_valid": 1},
        {"validation_error_types": "missing"},
        {"validation_error_types": [1]},
        {"error_code": 5},
        {"now": datetime(2026, 11, 3, 12, 0)},
        {"record_id": "x"},
    ],
)
async def test_settle_usage_record_rejects_bad_input(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await repo.settle_usage_record(SESSION, **_settle_args(**overrides))


@pytest.mark.parametrize("overrides", [
    {"outcome": "abandoned"},
    {"cost_micro_usd": -1},
    {"reserved_estimate_micro_usd": -1},
    {"reserved_estimate_micro_usd": True},
    {"limit_micro_usd": -1},
    {"limit_micro_usd": 1.5},
    {"budget_row_id": "x"},
    {"now": datetime(2026, 11, 3, 12, 0)},
])
async def test_settle_rejects_bad_input(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        await repo.settle(SESSION, **_settle_full_args(**overrides))


@pytest.mark.parametrize("bad", BAD_MONEY)
async def test_settle_budget_rejects_bad_money(bad: Any) -> None:
    for position in range(3):
        values: list[Any] = [10, 10, 1000]
        values[position] = bad
        with pytest.raises(ValueError):
            await repo.settle_budget(SESSION, ROW, values[0], values[1], values[2], NOW)


async def test_settle_budget_rejects_naive_time() -> None:
    with pytest.raises(ValueError):
        await repo.settle_budget(SESSION, ROW, 1, 1, 1000, datetime(2026, 11, 3))


async def test_abandon_rejects_naive_time_and_bad_id() -> None:
    with pytest.raises(ValueError):
        await repo.abandon_usage_record(SESSION, REC, datetime(2026, 11, 3))
    with pytest.raises(ValueError):
        await repo.abandon_usage_record(SESSION, "x", NOW)  # type: ignore[arg-type]


async def test_reconciliation_and_get_reject_bad_ids() -> None:
    with pytest.raises(ValueError):
        await repo.reconciliation_query(SESSION, ["x"])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        await repo.get_budget_row(SESSION, "x")  # type: ignore[arg-type]


def test_budget_row_snapshot_is_frozen() -> None:
    snapshot = repo.BudgetRowSnapshot(
        id=UUID(int=1),
        scope="system",
        workspace_id=None,
        period_start=PERIOD,
        limit_micro_usd=1,
        reserved_micro_usd=0,
        spent_micro_usd=0,
        warning_notified_at=None,
        exhausted_notified_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.spent_micro_usd = 5  # type: ignore[misc]
