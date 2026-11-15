"""AiBudgetService: read-only budget status of one workspace (spec 5.5, 6, D-18).

INTERNAL module; the class is exported from the package root. It reads in its own short read-only
session and never writes or commits. Time comes from the injected ``Clock`` (INV-22). Money is an
``int`` in micro-USD throughout.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as repo
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.context import AiCallContext
from app.ai_platform.usage_types import AiBudgetStatus, BudgetState
from app.core import Clock

WORKSPACE_CONTEXT_REQUIRED = "a workspace-scoped AiCallContext is required"
WARNING_PERCENT = 80


def require_workspace_id(ctx: AiCallContext) -> UUID:
    """The workspace of a context, or ``ValueError`` for a system context (spec 15)."""
    if ctx.is_system or ctx.workspace_id is None:
        raise ValueError(WORKSPACE_CONTEXT_REQUIRED)
    return ctx.workspace_id


def compute_state(*, limit: int, spent: int, reserved: int) -> BudgetState:
    """D-18: from the counters and the current limit only. The notification flags are not used."""
    if spent + reserved >= limit:
        return "exhausted"
    if spent * 100 >= WARNING_PERCENT * limit:
        return "warning"
    return "ok"


def compute_percent_used(*, limit: int, spent: int) -> int:
    """``floor(100 * spent / limit)`` on settled spend. A limit of 0 reports 100."""
    if limit == 0:
        return 100
    return (100 * spent) // limit


def build_status(*, period_start: date, limit: int, spent: int, reserved: int) -> AiBudgetStatus:
    return AiBudgetStatus(
        period_start=period_start,
        limit_micro_usd=limit,
        spent_micro_usd=spent,
        reserved_micro_usd=reserved,
        remaining_micro_usd=max(0, limit - spent - reserved),
        percent_used=compute_percent_used(limit=limit, spent=spent),
        state=compute_state(limit=limit, spent=spent, reserved=reserved),
    )


class AiBudgetService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        config: AiPlatformConfig,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._config = config

    async def get_status(self, ctx: AiCallContext) -> AiBudgetStatus:
        """Budget status of the context's workspace for the current UTC month."""
        workspace_id = require_workspace_id(ctx)
        period_start = repo.period_start_for(self._clock.now())
        async with self._sessions() as session:  # read only; closing it rolls back, never commits
            await session.execute(text("SET TRANSACTION READ ONLY"))
            row = await repo.find_workspace_budget_row(session, workspace_id, period_start)
        spent = 0 if row is None else row.spent_micro_usd
        reserved = 0 if row is None else row.reserved_micro_usd
        return build_status(
            period_start=period_start,
            limit=self._config.workspace_limit_micro_usd,
            spent=spent,
            reserved=reserved,
        )
