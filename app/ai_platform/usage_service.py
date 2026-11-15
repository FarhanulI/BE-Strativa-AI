"""AiUsageService: read-only usage report of one workspace and month (spec 5.5, 6, 15).

INTERNAL module; the class is exported from the package root. Every read is
``WHERE workspace_id = ctx.workspace_id AND period_start = :period_start``, so system-scope rows
(``workspace_id IS NULL``) and other workspaces are never included. Rows still ``reserved`` (in
flight) are excluded. Never returns a per-call row, a prompt, a completion or other content.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as repo
from app.ai_platform.budget_service import require_workspace_id
from app.ai_platform.context import AiCallContext
from app.ai_platform.usage_types import AiUsageGroup, AiUsageReport, AiUsageTotals, UsageGroupBy
from app.core import Clock, ValidationFailed

PERIOD_NOT_FIRST_OF_MONTH = "period_start must be the first day of a month"
FUTURE_PERIOD = "period_start must not be after the current month"
BAD_GROUP_BY = "group_by must be task, model or day"

# Fixed SQL fragments, chosen from this table only (never built from a caller value).
_KEY_SQL: dict[str, str] = {
    "task": "task",
    "model": "model",
    "day": "CAST((started_at AT TIME ZONE 'UTC') AS date)",
}


class AiUsageService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def get_workspace_usage(
        self, ctx: AiCallContext, *, period_start: date, group_by: UsageGroupBy
    ) -> AiUsageReport:
        workspace_id = require_workspace_id(ctx)
        if group_by not in _KEY_SQL:
            raise ValueError(BAD_GROUP_BY)
        if type(period_start) is not date or period_start.day != 1:
            raise ValueError(PERIOD_NOT_FIRST_OF_MONTH)
        if period_start > repo.period_start_for(self._clock.now()):
            raise ValidationFailed(FUTURE_PERIOD)

        key_sql = _KEY_SQL[group_by]
        statement = text(
            f"SELECT {key_sql} AS group_key, count(*) AS call_count, "
            "count(*) FILTER (WHERE status IN ('failed', 'abandoned')) AS failed_call_count, "
            "COALESCE(sum(input_units), 0) AS input_units, "
            "COALESCE(sum(output_units), 0) AS output_units, "
            "COALESCE(sum(cost_micro_usd), 0) AS cost_micro_usd "
            "FROM ai_usage_records "
            "WHERE workspace_id = :workspace_id AND period_start = :period_start "
            "AND status <> 'reserved' "
            f"GROUP BY {key_sql}"
        )
        async with self._sessions() as session:  # read only; closing it rolls back, never commits
            await session.execute(text("SET TRANSACTION READ ONLY"))
            rows = (
                await session.execute(
                    statement, {"workspace_id": workspace_id, "period_start": period_start}
                )
            ).all()

        groups = sorted(
            (
                AiUsageGroup(
                    key=row.group_key.isoformat() if group_by == "day" else str(row.group_key),
                    call_count=int(row.call_count),
                    failed_call_count=int(row.failed_call_count),
                    input_units=int(row.input_units),
                    output_units=int(row.output_units),
                    cost_micro_usd=int(row.cost_micro_usd),
                )
                for row in rows
            ),
            key=lambda group: group.key,
        )
        totals = AiUsageTotals(
            call_count=sum(g.call_count for g in groups),
            failed_call_count=sum(g.failed_call_count for g in groups),
            input_units=sum(g.input_units for g in groups),
            output_units=sum(g.output_units for g in groups),
            cost_micro_usd=sum(g.cost_micro_usd for g in groups),
        )
        return AiUsageReport(period_start=period_start, totals=totals, groups=groups)
