"""Database tests for AiBudgetService and AiUsageService (ai_platform step 3c).

Covers AC-33 (state part, D-18), AC-35 (state part), AC-52 (scoping and privacy parts), INV-19,
INV-21, INV-22.

Isolation: like the earlier db tests, every test commits real rows through separate sessions, so
none can use the rollback fixture. Each test builds its own workspaces and requests with fresh ids
and a private calendar year (system-scope budget rows have no workspace to cascade from). Teardown
deletes ONLY what the test created or caused, by id, and checks that nothing is left. Nothing is
truncated. The audit rows that budget events leave behind are removed through
``tests.helpers.audit_teardown`` (marker check, trigger re-enabled and verified).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import (
    AiBudgetService,
    AiCallContext,
    AiPlatformConfig,
    AiUsageService,
)
from app.ai_platform import budget_repository as repo
from app.ai_platform.budget_coordinator import (
    BudgetCoordinator,
    ReservationParams,
    ReservationResult,
    SettlementOutcome,
)
from app.ai_platform.errors import AiBudgetExceeded
from app.core import FakeClock, Settings, SystemClock, UUID7Factory, ValidationFailed
from app.db_migrations.engine import build_async_engine
from app.workspace.models import Workspace
from tests.helpers.audit_teardown import delete_audit_rows

pytestmark = pytest.mark.db

SENTINEL = "zq9-sentinel-unrelated-4e7b"
TASK_BRIEF = "GENERATE_BRIEF_DRAFT"
TASK_HOOK = "GENERATE_HOOK_VARIATIONS"
MODEL_ONE = "fake-chat-zq1"
MODEL_TWO = "fake-chat-zq2"
LIMIT = 1_000


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


def _config(workspace_micro: int, system_micro: int | None = None) -> AiPlatformConfig:
    system = workspace_micro if system_micro is None else system_micro
    return AiPlatformConfig(
        workspace_monthly_budget_usd=f"{Decimal(workspace_micro) / Decimal(1_000_000):.6f}",
        system_monthly_budget_usd=f"{Decimal(system) / Decimal(1_000_000):.6f}",
    )


@dataclass
class Env:
    sessions: async_sessionmaker[AsyncSession]
    year: int
    workspaces: list[UUID] = field(default_factory=list)
    requests: list[UUID] = field(default_factory=list)
    budget_rows: list[UUID] = field(default_factory=list)
    attempts: dict[UUID, int] = field(default_factory=dict)

    def clock(self, month: int = 6, day: int = 20) -> FakeClock:
        return FakeClock(datetime(self.year, month, day, 12, 0, tzinfo=UTC))

    def period(self, month: int = 6) -> date:
        return date(self.year, month, 1)

    def budget(self, clock: FakeClock, limit: int = LIMIT) -> AiBudgetService:
        return AiBudgetService(self.sessions, clock, _config(limit))

    def usage(self, clock: FakeClock) -> AiUsageService:
        return AiUsageService(self.sessions, clock)

    def coordinator(self, clock: FakeClock, limit: int = LIMIT) -> BudgetCoordinator:
        return BudgetCoordinator(self.sessions, clock, _config(limit))

    async def new_workspace(self) -> UUID:
        async with self.sessions() as session, session.begin():
            workspace = Workspace(name="readsvc-test", slug=f"readsvc-{_new_id()}")
            session.add(workspace)
            await session.flush()
            workspace_id = workspace.id
        self.workspaces.append(workspace_id)
        return workspace_id

    async def new_request(self, workspace_id: UUID | None, clock: FakeClock) -> UUID:
        request_id = _new_id()
        system = workspace_id is None
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO ai_requests (id, scope, workspace_id, actor_type, task, "
                    "output_schema_name, output_schema_version, mode, status, "
                    "correlation_request_id, started_at) VALUES (:id, :scope, :workspace_id, "
                    ":actor, :task, :schema, :version, 'sync', 'running', :correlation, :now)"
                ),
                {
                    "id": request_id,
                    "scope": "system" if system else "workspace",
                    "workspace_id": workspace_id,
                    "actor": "system" if system else "user",
                    "task": "EMBED_TEXT" if system else TASK_HOOK,
                    "schema": None if system else "HookVariationSet",
                    "version": None if system else 1,
                    "correlation": SENTINEL,
                    "now": clock.now(),
                },
            )
        self.requests.append(request_id)
        return request_id

    async def reserve(
        self, coordinator: BudgetCoordinator, workspace_id: UUID | None, clock: FakeClock, est: int
    ) -> ReservationResult:
        request_id = await self.new_request(workspace_id, clock)
        system = workspace_id is None
        scope: repo.Scope = "system" if system else "workspace"
        result = await coordinator.reserve_for_call(
            scope,
            workspace_id,
            est,
            ReservationParams(
                request_id=request_id,
                attempt_no=1,
                task="EMBED_TEXT" if system else TASK_HOOK,
                call_kind="embedding" if system else "generation",
                provider="fakeprov",
                model=MODEL_ONE,
                catalog_version="test-1",
                price_version="test-prices-1",
                billing_mode="paid",
                routing_version="r1",
                route_rank=1,
                candidate_snapshot=[{"model": MODEL_ONE, "eligible": True, "reason_code": None}],
            ),
        )
        if result.budget_row_id not in self.budget_rows:
            self.budget_rows.append(result.budget_row_id)
        return result

    async def settle(
        self,
        coordinator: BudgetCoordinator,
        result: ReservationResult,
        scope: repo.Scope,
        est: int,
        cost: int,
    ) -> None:
        await coordinator.settle_call(
            result.usage_record_id,
            result.budget_row_id,
            est,
            SettlementOutcome(
                outcome="succeeded",
                input_units=10,
                output_units=20,
                cost_micro_usd=cost,
                finish_reason="stop",
                schema_valid=True,
                validation_error_count=0,
                validation_error_types=[],
                latency_ms=5,
            ),
            coordinator.limit_for_scope(scope),
        )

    async def insert_usage(
        self,
        request_id: UUID,
        workspace_id: UUID | None,
        *,
        task: str,
        model: str,
        status: str,
        started_at: datetime,
        input_units: int | None,
        output_units: int | None,
        cost: int,
        period_start: date,
    ) -> None:
        attempt = self.attempts.get(request_id, 0) + 1
        self.attempts[request_id] = attempt
        settled = status != "reserved"
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO ai_usage_records (id, request_id, attempt_no, scope, "
                    "workspace_id, task, call_kind, provider, model, catalog_version, "
                    "price_version, billing_mode, routing_version, route_rank, "
                    "candidate_snapshot, status, error_code, finish_reason, input_units, "
                    "output_units, reserved_micro_usd, cost_micro_usd, period_start, "
                    "started_at, finished_at) VALUES (:id, :request_id, :attempt, :scope, "
                    ":workspace_id, :task, 'generation', :sentinel, :model, :sentinel, "
                    "'test-prices-1', 'paid', 'r1', 1, CAST('[]' AS jsonb), :status, "
                    ":sentinel, :sentinel, :input_units, :output_units, 999, :cost, "
                    ":period_start, :started_at, :finished_at)"
                ),
                {
                    "id": _new_id(),
                    "request_id": request_id,
                    "attempt": attempt,
                    "scope": "system" if workspace_id is None else "workspace",
                    "workspace_id": workspace_id,
                    "task": task,
                    "sentinel": SENTINEL,
                    "model": model,
                    "status": status,
                    "input_units": input_units,
                    "output_units": output_units,
                    "cost": cost,
                    "period_start": period_start,
                    "started_at": started_at,
                    "finished_at": started_at if settled else None,
                },
            )

    async def budget_row(self, workspace_id: UUID, period: date) -> repo.BudgetRowSnapshot | None:
        async with self.sessions() as session, session.begin():
            return await repo.find_workspace_budget_row(session, workspace_id, period)

    async def count_budget_rows(self, workspace_id: UUID) -> int:
        async with self.sessions() as session, session.begin():
            return (
                await session.execute(
                    text("SELECT count(*) FROM ai_budget_periods WHERE workspace_id = :w"),
                    {"w": workspace_id},
                )
            ).scalar_one()

    async def cleanup(self) -> None:
        start, end = date(self.year, 1, 1), date(self.year + 1, 1, 1)
        async with self.sessions() as session, session.begin():
            found = await session.execute(
                text(
                    "SELECT id FROM ai_budget_periods "
                    "WHERE (scope = 'system' AND period_start >= :s AND period_start < :e) "
                    "   OR workspace_id = ANY(CAST(:w AS uuid[]))"
                ),
                {"s": start, "e": end, "w": self.workspaces},
            )
            for (row_id,) in found.all():
                if row_id not in self.budget_rows:
                    self.budget_rows.append(row_id)
            await session.execute(
                text(
                    "DELETE FROM outbox_events WHERE aggregate_type = 'ai_budget' "
                    "AND aggregate_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": self.budget_rows},
            )
            await delete_audit_rows(
                session,
                resource_type="ai_budget",
                resource_ids=[str(row_id) for row_id in self.budget_rows],
            )
            for table, ids in (
                ("ai_requests", self.requests),  # cascades to ai_usage_records
                ("ai_budget_periods", self.budget_rows),
                ("workspaces", self.workspaces),
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE id = ANY(CAST(:ids AS uuid[]))"),
                    {"ids": ids},
                )
        async with self.sessions() as session, session.begin():
            leftovers = (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM ai_requests WHERE id = ANY(CAST(:r AS uuid[]))) + "
                        "(SELECT count(*) FROM ai_usage_records "
                        "   WHERE request_id = ANY(CAST(:r AS uuid[]))) + "
                        "(SELECT count(*) FROM ai_budget_periods "
                        "   WHERE id = ANY(CAST(:b AS uuid[])) "
                        "      OR workspace_id = ANY(CAST(:w AS uuid[]))) + "
                        "(SELECT count(*) FROM outbox_events "
                        "   WHERE aggregate_id = ANY(CAST(:b AS uuid[]))) + "
                        "(SELECT count(*) FROM audit_log WHERE resource_type = 'ai_budget' "
                        "   AND resource_id = ANY(CAST(:bs AS text[]))) + "
                        "(SELECT count(*) FROM workspaces WHERE id = ANY(CAST(:w AS uuid[])))"
                    ),
                    {
                        "r": self.requests,
                        "b": self.budget_rows,
                        "bs": [str(row_id) for row_id in self.budget_rows],
                        "w": self.workspaces,
                    },
                )
            ).scalar_one()
        assert leftovers == 0, "test left rows behind"


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[Env]:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True),
        pooled=False,
        engine_options={"pool_size": 10, "max_overflow": 0},
    )
    environment = Env(
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        year=2200 + secrets.randbelow(2000),
    )
    try:
        yield environment
    finally:
        try:
            await environment.cleanup()
        finally:
            await engine.dispose()


def _worker(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="req-read")


# --------------------------------------------------------------------------------------------
# AC-33 (state part) / AC-35 (state part) / D-18
# --------------------------------------------------------------------------------------------


async def test_state_follows_the_counters_and_the_current_limit(env: Env) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    ctx = _worker(workspace_id)
    coordinator = env.coordinator(clock)
    service = env.budget(clock)

    first = await env.reserve(coordinator, workspace_id, clock, 500)
    status = await service.get_status(ctx)
    assert (status.state, status.spent_micro_usd, status.reserved_micro_usd) == ("ok", 0, 500)
    assert status.remaining_micro_usd == 500
    await env.settle(coordinator, first, "workspace", 500, 500)
    second = await env.reserve(coordinator, workspace_id, clock, 299)
    await env.settle(coordinator, second, "workspace", 299, 299)
    status = await service.get_status(ctx)
    assert (status.spent_micro_usd, status.percent_used, status.state) == (799, 79, "ok")

    third = await env.reserve(coordinator, workspace_id, clock, 1)
    await env.settle(coordinator, third, "workspace", 1, 1)  # settled spent reaches exactly 80 %
    status = await service.get_status(ctx)
    assert (status.spent_micro_usd, status.percent_used, status.state) == (800, 80, "warning")

    await env.reserve(coordinator, workspace_id, clock, 150)  # 950 < limit: still warning
    assert (await service.get_status(ctx)).state == "warning"
    await env.reserve(coordinator, workspace_id, clock, 50)  # spent + reserved == limit
    status = await service.get_status(ctx)
    assert (status.state, status.remaining_micro_usd) == ("exhausted", 0)
    assert (status.spent_micro_usd, status.reserved_micro_usd) == (800, 200)

    with pytest.raises(AiBudgetExceeded):
        await env.reserve(coordinator, workspace_id, clock, 1)
    before = await env.budget_row(workspace_id, env.period())
    assert before is not None
    assert before.exhausted_notified_at is not None
    assert before.warning_notified_at is not None

    # Raise the configured limit: the state follows at once, the flags stay set (D-18).
    raised = await env.budget(clock, 2_000).get_status(ctx)
    assert raised.limit_micro_usd == 2_000
    assert raised.state == "ok"
    assert raised.percent_used == 40
    assert raised.remaining_micro_usd == 1_000
    after = await env.budget_row(workspace_id, env.period())
    assert after is not None
    assert after.exhausted_notified_at == before.exhausted_notified_at
    assert after.warning_notified_at == before.warning_notified_at

    # Lowering the limit below spent + reserved makes it exhausted.
    lowered = await env.budget(clock, 900).get_status(ctx)
    assert lowered.state == "exhausted"
    assert lowered.limit_micro_usd == 900
    assert lowered.remaining_micro_usd == 0


async def test_a_limit_change_moves_exhausted_to_warning_or_ok_at_once(env: Env) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock)
    ctx = _worker(workspace_id)
    settled = await env.reserve(coordinator, workspace_id, clock, 850)
    await env.settle(coordinator, settled, "workspace", 850, 850)
    await env.reserve(coordinator, workspace_id, clock, 150)  # in flight: spent + reserved == 1000

    assert (await env.budget(clock, 1_000).get_status(ctx)).state == "exhausted"
    # 1000 < 1050 and 85000 >= 80 * 1050 (84000): warning
    assert (await env.budget(clock, 1_050).get_status(ctx)).state == "warning"
    # 85000 < 80 * 1100 (88000): ok
    assert (await env.budget(clock, 1_100).get_status(ctx)).state == "ok"


async def test_a_workspace_without_a_row_reports_the_configured_limit(env: Env) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    status = await env.budget(clock, 25_000_000).get_status(_worker(workspace_id))
    assert status.currency == "USD"
    assert status.period_start == env.period()
    assert status.limit_micro_usd == 25_000_000
    assert (status.spent_micro_usd, status.reserved_micro_usd) == (0, 0)
    assert (status.remaining_micro_usd, status.percent_used, status.state) == (
        25_000_000,
        0,
        "ok",
    )
    assert await env.count_budget_rows(workspace_id) == 0  # the read never writes


async def test_status_uses_the_clock_month_and_ignores_other_months(env: Env) -> None:
    workspace_id = await env.new_workspace()
    june, july = env.clock(6), env.clock(7, 1)
    coordinator = env.coordinator(june)
    result = await env.reserve(coordinator, workspace_id, june, 100)
    await env.settle(coordinator, result, "workspace", 100, 100)
    ctx = _worker(workspace_id)
    assert (await env.budget(june).get_status(ctx)).spent_micro_usd == 100
    next_month = await env.budget(july).get_status(ctx)
    assert next_month.period_start == env.period(7)
    assert (next_month.spent_micro_usd, next_month.state) == (0, "ok")


# --------------------------------------------------------------------------------------------
# INV-19 / AC-52: scoping
# --------------------------------------------------------------------------------------------


async def test_reads_never_include_another_workspace_or_the_system_row(env: Env) -> None:
    clock = env.clock()
    coordinator = env.coordinator(clock)
    workspace_a = await env.new_workspace()
    workspace_b = await env.new_workspace()

    a = await env.reserve(coordinator, workspace_a, clock, 100)
    await env.settle(coordinator, a, "workspace", 100, 100)
    b = await env.reserve(coordinator, workspace_b, clock, 200)
    await env.settle(coordinator, b, "workspace", 200, 200)
    await env.reserve(coordinator, workspace_b, clock, 50)  # in flight for B
    system = await env.reserve(coordinator, None, clock, 300)
    await env.settle(coordinator, system, "system", 300, 300)

    status_a = await env.budget(clock).get_status(_worker(workspace_a))
    assert (status_a.spent_micro_usd, status_a.reserved_micro_usd) == (100, 0)
    status_b = await env.budget(clock).get_status(_worker(workspace_b))
    assert (status_b.spent_micro_usd, status_b.reserved_micro_usd) == (200, 50)

    report_a = await env.usage(clock).get_workspace_usage(
        _worker(workspace_a), period_start=env.period(), group_by="task"
    )
    assert report_a.totals.model_dump() == {
        "call_count": 1,
        "failed_call_count": 0,
        "input_units": 10,
        "output_units": 20,
        "cost_micro_usd": 100,
    }
    assert [(g.key, g.call_count, g.cost_micro_usd) for g in report_a.groups] == [
        (TASK_HOOK, 1, 100)
    ]
    report_b = await env.usage(clock).get_workspace_usage(
        _worker(workspace_b), period_start=env.period(), group_by="task"
    )  # B's in-flight record is excluded
    assert (report_b.totals.call_count, report_b.totals.cost_micro_usd) == (1, 200)

    system_ctx = AiCallContext.system(request_id="req-sys")
    with pytest.raises(ValueError):
        await env.budget(clock).get_status(system_ctx)
    with pytest.raises(ValueError):
        await env.usage(clock).get_workspace_usage(
            system_ctx, period_start=env.period(), group_by="task"
        )


# --------------------------------------------------------------------------------------------
# Usage aggregation
# --------------------------------------------------------------------------------------------


@dataclass
class Seeded:
    workspace_id: UUID
    other_id: UUID


async def _seed(env: Env, clock: FakeClock) -> Seeded:
    workspace_id = await env.new_workspace()
    other_id = await env.new_workspace()
    request = await env.new_request(workspace_id, clock)
    other_request = await env.new_request(other_id, clock)
    system_request = await env.new_request(None, clock)
    june, may = env.period(6), env.period(5)

    def at(month: int, day: int, h: int = 0, m: int = 0, s: int = 0) -> datetime:
        return datetime(env.year, month, day, h, m, s, tzinfo=UTC)

    async def add(**values: Any) -> None:
        await env.insert_usage(request, workspace_id, period_start=june, **values)

    await add(
        task=TASK_HOOK,
        model=MODEL_ONE,
        status="succeeded",
        started_at=at(6, 1, 10),
        input_units=100,
        output_units=50,
        cost=1000,
    )
    await add(
        task=TASK_HOOK,
        model=MODEL_ONE,
        status="failed",
        started_at=at(6, 1, 23, 59, 59),
        input_units=20,
        output_units=None,
        cost=200,
    )
    await add(
        task=TASK_HOOK,
        model=MODEL_TWO,
        status="abandoned",
        started_at=at(6, 2),
        input_units=None,
        output_units=None,
        cost=500,
    )
    await add(
        task=TASK_BRIEF,
        model=MODEL_TWO,
        status="succeeded",
        started_at=at(6, 2, 12),
        input_units=7,
        output_units=3,
        cost=70,
    )
    await add(
        task=TASK_BRIEF,
        model=MODEL_ONE,
        status="reserved",
        started_at=at(6, 2, 13),
        input_units=None,
        output_units=None,
        cost=0,
    )  # in flight: excluded
    await add(
        task=TASK_BRIEF,
        model=MODEL_TWO,
        status="succeeded",
        started_at=at(6, 30, 23, 59, 59),
        input_units=1,
        output_units=1,
        cost=10,
    )
    plus_two = timezone(timedelta(hours=2))  # 01:30 +02:00 on the 3rd is 23:30 UTC on the 2nd
    await add(
        task=TASK_HOOK,
        model=MODEL_ONE,
        status="succeeded",
        started_at=datetime(env.year, 6, 3, 1, 30, tzinfo=plus_two),
        input_units=1,
        output_units=1,
        cost=5,
    )
    # Another period of the same workspace (a past month).
    await env.insert_usage(
        request,
        workspace_id,
        task=TASK_BRIEF,
        model=MODEL_ONE,
        status="succeeded",
        started_at=at(5, 31, 12),
        input_units=40,
        output_units=60,
        cost=700,
        period_start=may,
    )
    # Another workspace and the system scope, same period and same task and model names.
    await env.insert_usage(
        other_request,
        other_id,
        task=TASK_HOOK,
        model=MODEL_ONE,
        status="succeeded",
        started_at=at(6, 2, 9),
        input_units=9_000,
        output_units=9_000,
        cost=90_000,
        period_start=june,
    )
    await env.insert_usage(
        system_request,
        None,
        task="EMBED_TEXT",
        model=MODEL_ONE,
        status="succeeded",
        started_at=at(6, 2, 9),
        input_units=8_000,
        output_units=0,
        cost=80_000,
        period_start=june,
    )
    return Seeded(workspace_id, other_id)


def _row(group: Any) -> tuple[str, int, int, int, int, int]:
    return (
        group.key,
        group.call_count,
        group.failed_call_count,
        group.input_units,
        group.output_units,
        group.cost_micro_usd,
    )


async def test_usage_aggregation_for_all_three_groupings(env: Env) -> None:
    clock = env.clock()
    seeded = await _seed(env, clock)
    ctx = _worker(seeded.workspace_id)
    service = env.usage(clock)
    year = env.year

    by_task = await service.get_workspace_usage(ctx, period_start=env.period(), group_by="task")
    by_model = await service.get_workspace_usage(ctx, period_start=env.period(), group_by="model")
    by_day = await service.get_workspace_usage(ctx, period_start=env.period(), group_by="day")

    totals = {
        "call_count": 6,  # reserved excluded; succeeded, failed and abandoned counted
        "failed_call_count": 2,  # failed and abandoned
        "input_units": 129,  # NULL counts as 0
        "output_units": 55,
        "cost_micro_usd": 1785,
    }
    for report in (by_task, by_model, by_day):
        assert report.period_start == env.period()
        assert report.totals.model_dump() == totals

    assert [_row(g) for g in by_task.groups] == [
        (TASK_BRIEF, 2, 0, 8, 4, 80),
        (TASK_HOOK, 4, 2, 121, 51, 1705),
    ]
    assert [_row(g) for g in by_model.groups] == [
        (MODEL_ONE, 3, 1, 121, 51, 1205),
        (MODEL_TWO, 3, 1, 8, 4, 580),
    ]
    assert [_row(g) for g in by_day.groups] == [
        (f"{year}-06-01", 2, 1, 120, 50, 1200),  # includes 23:59:59 UTC
        (f"{year}-06-02", 3, 1, 8, 4, 575),  # 00:00:00 UTC, and 01:30 +02:00 on the 3rd
        (f"{year}-06-30", 1, 0, 1, 1, 10),
    ]

    for report in (by_task, by_day):  # model ids appear only in the model grouping
        assert not any("fake-chat" in g.key for g in report.groups)
        assert SENTINEL not in report.model_dump_json()
    assert all(date.fromisoformat(g.key) for g in by_day.groups)


async def test_month_rules(env: Env) -> None:
    clock = env.clock()
    seeded = await _seed(env, clock)
    ctx = _worker(seeded.workspace_id)
    service = env.usage(clock)

    may = await service.get_workspace_usage(ctx, period_start=env.period(5), group_by="task")
    assert may.totals.model_dump() == {
        "call_count": 1,
        "failed_call_count": 0,
        "input_units": 40,
        "output_units": 60,
        "cost_micro_usd": 700,
    }
    assert [_row(g) for g in may.groups] == [(TASK_BRIEF, 1, 0, 40, 60, 700)]

    for group_by in ("task", "model", "day"):
        empty = await service.get_workspace_usage(
            ctx,
            period_start=env.period(4),
            group_by=group_by,  # type: ignore[arg-type]
        )
        assert empty.groups == []
        assert empty.totals.model_dump() == dict.fromkeys(
            ("call_count", "failed_call_count", "input_units", "output_units", "cost_micro_usd"), 0
        )

    with pytest.raises(ValidationFailed):
        await service.get_workspace_usage(ctx, period_start=env.period(7), group_by="task")
    with pytest.raises(ValueError):
        await service.get_workspace_usage(ctx, period_start=date(env.year, 6, 2), group_by="task")

    # The first of next month is allowed once the clock reaches it (FakeClock), and not before.
    clock.set(datetime(env.year, 6, 30, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(ValidationFailed):
        await service.get_workspace_usage(ctx, period_start=env.period(7), group_by="task")
    clock.set(datetime(env.year, 7, 1, 0, 0, 0, tzinfo=UTC))
    current = await service.get_workspace_usage(ctx, period_start=env.period(7), group_by="task")
    assert current.groups == []


# --------------------------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------------------------


async def test_results_carry_only_declared_fields_and_no_stored_text(env: Env) -> None:
    clock = env.clock()
    seeded = await _seed(env, clock)
    ctx = _worker(seeded.workspace_id)
    outputs: list[str] = []
    for group_by in ("task", "model", "day"):
        report = await env.usage(clock).get_workspace_usage(
            ctx,
            period_start=env.period(),
            group_by=group_by,  # type: ignore[arg-type]
        )
        payload = json.loads(report.model_dump_json())
        assert set(payload) == {"period_start", "totals", "groups"}
        assert set(payload["totals"]) == {
            "call_count",
            "failed_call_count",
            "input_units",
            "output_units",
            "cost_micro_usd",
        }
        assert all(
            set(g)
            == {
                "key",
                "call_count",
                "failed_call_count",
                "input_units",
                "output_units",
                "cost_micro_usd",
            }
            for g in payload["groups"]
        )
        outputs.append(report.model_dump_json())

    status = await env.budget(clock).get_status(ctx)
    status_payload = json.loads(status.model_dump_json())
    assert set(status_payload) == {
        "currency",
        "period_start",
        "limit_micro_usd",
        "spent_micro_usd",
        "reserved_micro_usd",
        "remaining_micro_usd",
        "percent_used",
        "state",
    }
    outputs.append(status.model_dump_json())
    assert all(SENTINEL not in output for output in outputs)
    assert all("fakeprov" not in output for output in outputs)
