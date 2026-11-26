"""Result types of the budget and usage services (spec 5.1, 6).

Frozen, ``extra="forbid"``, strict ints. All money is integer micro-USD. No field carries free text
other than the declared group ``key`` (a task name, a model id or an ISO day).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)

BudgetState = Literal["ok", "warning", "exhausted"]
UsageGroupBy = Literal["task", "model", "day"]


class AiUsageSummary(BaseModel):
    model_config = _STRICT

    input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    cost_micro_usd: int = Field(ge=0)
    call_count: int = Field(ge=0)


class AiBudgetStatus(BaseModel):
    model_config = _STRICT

    currency: Literal["USD"] = "USD"
    period_start: date
    limit_micro_usd: int = Field(ge=0)
    spent_micro_usd: int = Field(ge=0)
    reserved_micro_usd: int = Field(ge=0)
    remaining_micro_usd: int = Field(ge=0)
    percent_used: int = Field(ge=0)
    state: BudgetState


class AiUsageTotals(BaseModel):
    model_config = _STRICT

    call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    cost_micro_usd: int = Field(ge=0)


class AiUsageGroup(BaseModel):
    model_config = _STRICT

    key: str
    call_count: int = Field(ge=0)
    failed_call_count: int = Field(ge=0)
    input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    cost_micro_usd: int = Field(ge=0)


class AiUsageReport(BaseModel):
    model_config = _STRICT

    period_start: date
    totals: AiUsageTotals
    groups: list[AiUsageGroup]
