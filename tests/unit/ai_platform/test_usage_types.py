"""Result types of the budget and usage services (spec 5.1, 6): strict, frozen, exact fields."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.ai_platform.usage_types import (
    AiBudgetStatus,
    AiUsageGroup,
    AiUsageReport,
    AiUsageSummary,
    AiUsageTotals,
)

PERIOD = date(2026, 6, 1)

SUMMARY: dict[str, Any] = {
    "input_units": 1,
    "output_units": 2,
    "cost_micro_usd": 3,
    "call_count": 4,
}
STATUS: dict[str, Any] = {
    "currency": "USD",
    "period_start": PERIOD,
    "limit_micro_usd": 100,
    "spent_micro_usd": 10,
    "reserved_micro_usd": 5,
    "remaining_micro_usd": 85,
    "percent_used": 10,
    "state": "ok",
}
TOTALS: dict[str, Any] = {
    "call_count": 3,
    "failed_call_count": 1,
    "input_units": 10,
    "output_units": 20,
    "cost_micro_usd": 30,
}
GROUP: dict[str, Any] = {"key": "a", **TOTALS}

CASES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (AiUsageSummary, SUMMARY),
    (AiBudgetStatus, STATUS),
    (AiUsageTotals, TOTALS),
    (AiUsageGroup, GROUP),
    (AiUsageReport, {"period_start": PERIOD, "totals": TOTALS, "groups": [GROUP]}),
]


@pytest.mark.parametrize(("model", "values"), CASES, ids=lambda case: getattr(case, "__name__", ""))
def test_each_type_has_exactly_the_spec_fields(
    model: type[BaseModel], values: dict[str, Any]
) -> None:
    assert set(model.model_fields) == set(values)
    instance = model(**values)
    with pytest.raises(ValidationError):
        model(**values, extra_field=1)
    first = next(iter(values))
    with pytest.raises(ValidationError):
        setattr(instance, first, values[first])  # frozen


@pytest.mark.parametrize(
    "model", [AiUsageSummary, AiBudgetStatus, AiUsageTotals, AiUsageGroup], ids=lambda m: m.__name__
)
def test_integer_fields_are_strict_and_non_negative(model: type[BaseModel]) -> None:
    values = dict(next(v for m, v in CASES if m is model))
    int_fields = [name for name, field in model.model_fields.items() if field.annotation is int]
    assert int_fields
    for name in int_fields:
        for bad in ("5", 5.0, True, -1):
            with pytest.raises(ValidationError):
                model(**{**values, name: bad})


def test_currency_is_the_constant_usd() -> None:
    assert AiBudgetStatus(**STATUS).currency == "USD"
    with pytest.raises(ValidationError):
        AiBudgetStatus(**{**STATUS, "currency": "EUR"})


@pytest.mark.parametrize("state", ["ok", "warning", "exhausted"])
def test_state_accepts_the_three_literals(state: str) -> None:
    assert AiBudgetStatus(**{**STATUS, "state": state}).state == state


@pytest.mark.parametrize("state", ["OK", "exhausted ", "full", "", None])
def test_state_rejects_anything_else(state: object) -> None:
    with pytest.raises(ValidationError):
        AiBudgetStatus(**{**STATUS, "state": state})
