"""Database and concurrency tests for the budget repository (ai_platform step 3a).

Covers AC-30..AC-37 (database parts) and INV-7, INV-10, INV-11, INV-13, INV-14, INV-15.

Isolation: tests that need concurrency commit real rows through separate sessions, so they cannot
use the rollback fixture. Every test builds its own workspaces and requests with fresh ids and a
private calendar year (so system-scope budget rows, which have no workspace to cascade from, never
collide with real data). Teardown deletes ONLY the rows the test created, by id, and checks that
none remain. Nothing is truncated.

AC-58 (lock order with the request-row fence) is a later step and is not covered here.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as repo
from app.core import FakeClock, Settings, SystemClock, UUID7Factory
from app.db_migrations.engine import build_async_engine
from app.workspace.models import Workspace

pytestmark = pytest.mark.db

T = TypeVar("T")
POOL = 60
TIMEOUT_SECONDS = 60


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


@dataclass(frozen=True)
class Call:
    record_id: UUID
    request_id: UUID
    row_id: UUID
    estimate: int


@dataclass
class Env:
    engine: Any
    sessions: async_sessionmaker[AsyncSession]
    year: int
    workspaces: list[UUID] = field(default_factory=list)
    requests: list[UUID] = field(default_factory=list)
    budget_rows: list[UUID] = field(default_factory=list)

    def clock(self, month: int = 6, day: int = 15) -> FakeClock:
        return FakeClock(datetime(self.year, month, day, 12, 0, tzinfo=UTC))

    async def new_workspace(self) -> UUID:
        async with self.sessions() as session, session.begin():
            workspace = Workspace(name="budget-test", slug=f"budget-{_new_id()}")
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
                    ":actor, :task, :schema, :version, 'sync', 'running', 'req-test', :now)"
                ),
                {
                    "id": request_id,
                    "scope": "system" if system else "workspace",
                    "workspace_id": workspace_id,
                    "actor": "system" if system else "user",
                    "task": "EMBED_TEXT" if system else "GENERATE_HOOK_VARIATIONS",
                    "schema": None if system else "HookVariationSet",
                    "version": None if system else 1,
                    "now": clock.now(),
                },
            )
        self.requests.append(request_id)
        return request_id

    async def ensure(
        self, workspace_id: UUID | None, clock: FakeClock, limit: int
    ) -> UUID:
        now = clock.now()
        async with self.sessions() as session, session.begin():
            row_id = await repo.ensure_budget_row(
                session,
                "system" if workspace_id is None else "workspace",
                workspace_id,
                repo.period_start_for(now),
                limit,
                now,
            )
        self.budget_rows.append(row_id)
        return row_id

    async def row(self, row_id: UUID) -> repo.BudgetRowSnapshot:
        async with self.sessions() as session, session.begin():
            snapshot = await repo.get_budget_row(session, row_id)
        assert snapshot is not None
        return snapshot

    async def record(self, record_id: UUID) -> Any:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "SELECT status, cost_micro_usd, reserved_micro_usd, finished_at, "
                    "input_units, schema_valid FROM ai_usage_records WHERE id = :id"
                ),
                {"id": record_id},
            )
            return result.one()

    async def ledger_sum(self, workspace_id: UUID | None, period: date) -> int:
        async with self.sessions() as session, session.begin():
            value = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(cost_micro_usd), 0) FROM ai_usage_records "
                        "WHERE period_start = :period "
                        "AND request_id = ANY(CAST(:requests AS uuid[])) "
                        "AND workspace_id IS NOT DISTINCT FROM :workspace_id"
                    ),
                    {"period": period, "requests": self.requests, "workspace_id": workspace_id},
                )
            ).scalar_one()
        return int(value)

    async def reserve_call(
        self,
        row_id: UUID,
        workspace_id: UUID | None,
        estimate: int,
        limit: int,
        clock: FakeClock,
        attempt_no: int = 1,
    ) -> Call:
        request_id = await self.new_request(workspace_id, clock)
        now = clock.now()
        async with self.sessions() as session, session.begin():
            assert await repo.reserve(session, row_id, estimate, limit, now)
            record_id = await repo.insert_reserved_usage_record(
                session,
                repo.ReservedUsageRecord(
                    request_id=request_id,
                    attempt_no=attempt_no,
                    scope="system" if workspace_id is None else "workspace",
                    workspace_id=workspace_id,
                    task="EMBED_TEXT" if workspace_id is None else "GENERATE_HOOK_VARIATIONS",
                    call_kind="embedding" if workspace_id is None else "generation",
                    provider="fakeprov",
                    model="fake-chat-zq1",
                    catalog_version="test-1",
                    price_version="test-prices-1",
                    billing_mode="paid",
                    routing_version="r1",
                    route_rank=1,
                    candidate_snapshot=[
                        {"model": "fake-chat-zq1", "eligible": True, "reason_code": None}
                    ],
                    reserved_micro_usd=estimate,
                    period_start=repo.period_start_for(now),
                    started_at=now,
                ),
            )
        return Call(record_id, request_id, row_id, estimate)

    async def settle_call(
        self,
        call: Call,
        cost: int,
        limit: int,
        clock: FakeClock,
        outcome: str = "succeeded",
    ) -> repo.SettleResult:
        async with self.sessions() as session, session.begin():
            return await repo.settle(
                session,
                call.record_id,
                outcome,
                10,
                20,
                cost,
                None if outcome == "succeeded" else "provider_error",
                "stop" if outcome == "succeeded" else None,
                True if outcome == "succeeded" else None,
                0 if outcome == "succeeded" else None,
                [] if outcome == "succeeded" else None,
                50,
                call.row_id,
                call.estimate,
                limit,
                clock.now(),
            )

    async def abandon(self, call: Call, clock: FakeClock) -> bool:
        async with self.sessions() as session, session.begin():
            return await repo.abandon_usage_record(session, call.record_id, clock.now())

    async def concurrently(
        self, count: int, work: Callable[[AsyncSession, int], Awaitable[T]]
    ) -> list[T]:
        """Run ``work`` in ``count`` separate committed sessions released by one barrier."""
        barrier = asyncio.Barrier(count)

        async def one(index: int) -> T:
            async with self.sessions() as session, session.begin():
                await session.execute(text("SELECT 1"))  # take the connection before the barrier
                await barrier.wait()
                return await work(session, index)

        async with asyncio.timeout(TIMEOUT_SECONDS):
            return list(await asyncio.gather(*(one(i) for i in range(count))))

    async def cleanup(self) -> None:
        async with self.sessions() as session, session.begin():
            for table, ids in (
                ("ai_requests", self.requests),  # cascades to ai_usage_records
                ("ai_budget_periods", self.budget_rows),
                ("workspaces", self.workspaces),  # cascades to any remaining ai_* rows
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
                        "(SELECT count(*) FROM workspaces WHERE id = ANY(CAST(:w AS uuid[])))"
                    ),
                    {"r": self.requests, "b": self.budget_rows, "w": self.workspaces},
                )
            ).scalar_one()
        assert leftovers == 0, "test left rows behind"


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[Env]:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True),
        pooled=False,
        engine_options={"pool_size": POOL, "max_overflow": 0},
    )
    environment = Env(
        engine=engine,
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


# --------------------------------------------------------------------------------------------
# AC-30 / INV-10
# --------------------------------------------------------------------------------------------


async def test_concurrent_reservations_admit_exactly_k(env: Env) -> None:
    k, n, estimate = 5, 40, 100
    limit = k * estimate
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, limit)

    observed: list[int] = []
    stop = asyncio.Event()

    async def observer() -> None:
        while not stop.is_set():
            snapshot = await env.row(row_id)
            observed.append(snapshot.spent_micro_usd + snapshot.reserved_micro_usd)

    watcher = asyncio.create_task(observer())
    try:
        results = await env.concurrently(
            n, lambda session, _i: repo.reserve(session, row_id, estimate, limit, clock.now())
        )
    finally:
        stop.set()
        await watcher

    assert results.count(True) == k
    assert results.count(False) == n - k
    final = await env.row(row_id)
    assert final.reserved_micro_usd == k * estimate
    assert final.spent_micro_usd == 0
    assert observed, "the observer never read the row"
    assert max(observed) <= limit


async def test_reserve_boundary_is_inclusive(env: Env) -> None:
    clock = env.clock()
    row_id = await env.ensure(await env.new_workspace(), clock, 100)
    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_id, 100, 100, clock.now()) is True
        assert await repo.reserve(session, row_id, 1, 100, clock.now()) is False


async def test_repository_never_commits(env: Env) -> None:
    """Statements run inside the caller's transaction: a rollback by the caller undoes them."""
    clock = env.clock()
    workspace = await env.new_workspace()
    now = clock.now()
    period = repo.period_start_for(now)
    async with env.sessions() as session:
        await session.begin()
        row_id = await repo.ensure_budget_row(session, "workspace", workspace, period, 500, now)
        await repo.reserve(session, row_id, 10, 500, now)
        await session.rollback()
    async with env.sessions() as session, session.begin():
        assert await repo.get_budget_row(session, row_id) is None


# --------------------------------------------------------------------------------------------
# AC-31 / INV-11
# --------------------------------------------------------------------------------------------


async def test_budget_rows_are_separated_by_scope(env: Env) -> None:
    clock = env.clock()
    ws_a, ws_b = await env.new_workspace(), await env.new_workspace()
    limit = 10_000
    row_a = await env.ensure(ws_a, clock, limit)
    row_b = await env.ensure(ws_b, clock, limit)
    row_s = await env.ensure(None, clock, limit)

    b_before, s_before = await env.row(row_b), await env.row(row_s)
    call_a = await env.reserve_call(row_a, ws_a, 300, limit, clock)
    abandoned_a = await env.reserve_call(row_a, ws_a, 100, limit, clock)
    await env.settle_call(call_a, 250, limit, clock)
    assert await env.abandon(abandoned_a, clock) is True
    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_a, limit + 1, limit, clock.now()) is False
        assert await repo.record_refusal(session, row_a, limit, clock.now()) is True
    a_after = await env.row(row_a)
    assert a_after.spent_micro_usd == 350 and a_after.exhausted_notified_at is not None
    assert await env.row(row_b) == b_before
    assert await env.row(row_s) == s_before

    a_before = await env.row(row_a)
    b_before = await env.row(row_b)
    call_s = await env.reserve_call(row_s, None, 400, limit, clock)
    await env.settle_call(call_s, 400, limit, clock)
    system_after = await env.row(row_s)
    assert system_after.spent_micro_usd == 400
    assert await env.row(row_a) == a_before
    assert await env.row(row_b) == b_before


async def test_exhausting_one_budget_does_not_refuse_the_others(env: Env) -> None:
    clock = env.clock()
    ws_a, ws_b = await env.new_workspace(), await env.new_workspace()
    row_a = await env.ensure(ws_a, clock, 100)
    row_b = await env.ensure(ws_b, clock, 1000)
    row_s = await env.ensure(None, clock, 1000)
    now = clock.now()

    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_a, 100, 100, now) is True  # A is now full
        assert await repo.reserve(session, row_a, 1, 100, now) is False
        assert await repo.reserve(session, row_b, 500, 1000, now) is True
        assert await repo.reserve(session, row_s, 500, 1000, now) is True
        assert await repo.reserve(session, row_s, 500, 1000, now) is True  # system now full
        assert await repo.reserve(session, row_s, 1, 1000, now) is False
        assert await repo.reserve(session, row_b, 500, 1000, now) is True  # B unaffected


# --------------------------------------------------------------------------------------------
# AC-32
# --------------------------------------------------------------------------------------------


async def test_ensure_budget_row_creates_row_with_limit_and_zero_counters(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    workspace_row = await env.ensure(workspace, clock, 25_000_000)
    system_row = await env.ensure(None, clock, 100_000_000)

    w = await env.row(workspace_row)
    assert (w.scope, w.workspace_id, w.limit_micro_usd) == ("workspace", workspace, 25_000_000)
    s = await env.row(system_row)
    assert (s.scope, s.workspace_id, s.limit_micro_usd) == ("system", None, 100_000_000)
    for row in (w, s):
        assert row.reserved_micro_usd == 0 and row.spent_micro_usd == 0
        assert row.warning_notified_at is None and row.exhausted_notified_at is None
        assert row.period_start == repo.period_start_for(clock.now())


async def test_ensure_budget_row_twice_and_concurrently_yields_one_row(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    period = repo.period_start_for(clock.now())
    first = await env.ensure(workspace, clock, 500)
    second = await env.ensure(workspace, clock, 999)  # later limit does not replace the first
    assert first == second
    assert (await env.row(first)).limit_micro_usd == 500

    other = await env.new_workspace()
    ids = await env.concurrently(
        20,
        lambda session, _i: repo.ensure_budget_row(
            session, "workspace", other, period, 500, clock.now()
        ),
    )
    env.budget_rows.extend(set(ids))
    assert len(set(ids)) == 1
    async with env.sessions() as session, session.begin():
        count = (
            await session.execute(
                text("SELECT count(*) FROM ai_budget_periods WHERE workspace_id = :w"),
                {"w": other},
            )
        ).scalar_one()
    assert count == 1


async def test_concurrent_system_row_creation_yields_one_row(env: Env) -> None:
    clock = env.clock()
    period = repo.period_start_for(clock.now())
    ids = await env.concurrently(
        20,
        lambda session, _i: repo.ensure_budget_row(
            session, "system", None, period, 700, clock.now()
        ),
    )
    env.budget_rows.extend(set(ids))
    assert len(set(ids)) == 1


async def test_new_utc_month_starts_a_new_row_at_zero(env: Env) -> None:
    clock = FakeClock(datetime(env.year, 12, 31, 23, 59, tzinfo=UTC))
    workspace = await env.new_workspace()
    december = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(december, workspace, 400, 1000, clock)
    await env.settle_call(call, 300, 1000, clock)
    december_before = await env.row(december)
    assert december_before.spent_micro_usd == 300

    clock.advance(timedelta(minutes=2))  # 00:01 on 1 January
    january = await env.ensure(workspace, clock, 1000)
    assert january != december
    new = await env.row(january)
    assert new.period_start == date(env.year + 1, 1, 1)
    assert (new.spent_micro_usd, new.reserved_micro_usd) == (0, 0)  # no carry-over
    assert await env.row(december) == december_before


# --------------------------------------------------------------------------------------------
# AC-33 / D-9
# --------------------------------------------------------------------------------------------


async def test_mid_month_limit_change(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    l1, l2, l3 = 1000, 400, 2000
    row_id = await env.ensure(workspace, clock, l1)

    settled = await env.reserve_call(row_id, workspace, 200, l1, clock)
    await env.settle_call(settled, 200, l1, clock)
    in_flight = await env.reserve_call(row_id, workspace, 300, l1, clock, attempt_no=1)
    row = await env.row(row_id)
    assert (row.spent_micro_usd, row.reserved_micro_usd) == (200, 300)

    # Lower the limit below spent + reserved: the next reservation is refused using L2, although
    # the stored limit (L1) would have admitted it.
    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_id, 10, l2, clock.now()) is False
        assert await repo.record_refusal(session, row_id, l2, clock.now()) is True
    refused = await env.row(row_id)
    assert refused.limit_micro_usd == l2
    assert (refused.spent_micro_usd, refused.reserved_micro_usd) == (200, 300)
    exhausted_at = refused.exhausted_notified_at
    assert exhausted_at is not None

    # The in-flight reservation still settles; the 80 % check uses the limit passed with it:
    # 480 * 100 >= 80 * 400 holds for L2 (it would not for L1, 48000 < 80000).
    result = await env.settle_call(in_flight, 280, l2, clock)
    assert result == repo.SettleResult(flipped=True, warning_newly_set=True)
    after = await env.row(row_id)
    assert (after.spent_micro_usd, after.reserved_micro_usd) == (480, 0)
    assert after.limit_micro_usd == l2

    # Raise the limit: the reservation L2 would have refused is admitted at once.
    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_id, 100, l3, clock.now()) is True
    raised = await env.row(row_id)
    assert raised.limit_micro_usd == l3
    assert raised.reserved_micro_usd == 100

    # Flags are never reset by a limit change; a second refusal does not re-notify.
    assert raised.exhausted_notified_at == exhausted_at
    assert raised.warning_notified_at is not None
    async with env.sessions() as session, session.begin():
        assert await repo.record_refusal(session, row_id, l3, clock.now()) is False
    assert (await env.row(row_id)).exhausted_notified_at == exhausted_at


# --------------------------------------------------------------------------------------------
# AC-34 / INV-15 (warning)
# --------------------------------------------------------------------------------------------


async def test_reservations_alone_never_set_the_warning(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    for _ in range(9):  # 900 reserved = 90 % of the limit, nothing settled
        await env.reserve_call(row_id, workspace, 100, 1000, clock)
    row = await env.row(row_id)
    assert row.reserved_micro_usd == 900 and row.spent_micro_usd == 0
    assert row.warning_notified_at is None


async def test_warning_is_set_once_by_the_crossing_settlement(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    calls = [await env.reserve_call(row_id, workspace, 100, 1000, clock) for _ in range(9)]

    flags = []
    for call in calls[:8]:
        result = await env.settle_call(call, 100, 1000, clock)
        assert result.flipped is True
        flags.append(result.warning_newly_set)
    assert flags == [False] * 7 + [True]  # spent reaches 800 = 80 % on the 8th settlement
    assert (await env.row(row_id)).warning_notified_at is not None

    later = await env.settle_call(calls[8], 100, 1000, clock)
    assert later == repo.SettleResult(flipped=True, warning_newly_set=False)


async def test_concurrent_crossing_settlements_set_the_warning_once(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    calls = [await env.reserve_call(row_id, workspace, 100, 1000, clock) for _ in range(10)]
    for call in calls[:7]:  # settled spent is 700, below the threshold
        assert (await env.settle_call(call, 100, 1000, clock)).warning_newly_set is False

    async def settle(session: AsyncSession, index: int) -> repo.SettleResult:
        call = calls[7 + index]
        return await repo.settle(
            session, call.record_id, "succeeded", 1, 1, 100, None, "stop", True, 0, [], 5,
            call.row_id, call.estimate, 1000, clock.now(),
        )  # fmt: skip

    results = await env.concurrently(3, settle)
    assert all(result.flipped for result in results)
    assert [result.warning_newly_set for result in results].count(True) == 1
    final = await env.row(row_id)
    assert final.spent_micro_usd == 1000 and final.reserved_micro_usd == 0
    assert final.warning_notified_at is not None


# --------------------------------------------------------------------------------------------
# AC-35 / INV-15 (exhausted)
# --------------------------------------------------------------------------------------------


async def test_refusal_below_full_spend_flags_once_and_never_resets(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 950, 1000, clock)
    await env.settle_call(call, 950, 1000, clock)

    now = clock.now()
    async with env.sessions() as session, session.begin():
        assert await repo.reserve(session, row_id, 100, 1000, now) is False  # 50 left < 100
        assert await repo.record_refusal(session, row_id, 1000, now) is True
    first = await env.row(row_id)
    assert first.exhausted_notified_at == now and first.spent_micro_usd == 950

    later = clock.now() + timedelta(minutes=1)
    async with env.sessions() as session, session.begin():
        assert await repo.record_refusal(session, row_id, 1000, later) is False
    assert (await env.row(row_id)).exhausted_notified_at == now

    async with env.sessions() as session, session.begin():  # raising the limit resets nothing
        assert await repo.reserve(session, row_id, 100, 5000, later) is True
    assert (await env.row(row_id)).exhausted_notified_at == now


async def test_concurrent_refusals_flag_exactly_once(env: Env) -> None:
    clock = env.clock()
    row_id = await env.ensure(await env.new_workspace(), clock, 100)
    results = await env.concurrently(
        20, lambda session, _i: repo.record_refusal(session, row_id, 100, clock.now())
    )
    assert results.count(True) == 1
    assert (await env.row(row_id)).exhausted_notified_at is not None


# --------------------------------------------------------------------------------------------
# AC-37 / INV-7 / INV-14
# --------------------------------------------------------------------------------------------


async def test_insert_reserved_usage_record_stores_the_call(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 120, 1000, clock)
    record = await env.record(call.record_id)
    assert record.status == "reserved"
    assert record.reserved_micro_usd == 120 and record.cost_micro_usd == 0
    assert record.finished_at is None
    # one attempt number per request
    async with env.sessions() as session, session.begin():
        stored = (
            await session.execute(
                text(
                    "SELECT candidate_snapshot, period_start FROM ai_usage_records WHERE id = :id"
                ),
                {"id": call.record_id},
            )
        ).one()
    assert stored.candidate_snapshot == [
        {"model": "fake-chat-zq1", "eligible": True, "reason_code": None}
    ]
    assert stored.period_start == repo.period_start_for(clock.now())


async def test_settling_twice_changes_nothing_the_second_time(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 200, 1000, clock)

    first = await env.settle_call(call, 150, 1000, clock)
    assert first.flipped is True
    budget_after_first = await env.row(row_id)
    record_after_first = await env.record(call.record_id)
    assert (budget_after_first.spent_micro_usd, budget_after_first.reserved_micro_usd) == (150, 0)

    second = await env.settle_call(call, 999, 1000, clock)
    assert second == repo.SettleResult(flipped=False, warning_newly_set=False)
    assert await env.row(row_id) == budget_after_first
    assert tuple(await env.record(call.record_id)) == tuple(record_after_first)


async def test_failed_settlement_with_zero_cost_releases_the_reservation(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 200, 1000, clock)
    result = await env.settle_call(call, 0, 1000, clock, outcome="failed")
    assert result.flipped is True
    row = await env.row(row_id)
    assert (row.spent_micro_usd, row.reserved_micro_usd) == (0, 0)
    assert (await env.record(call.record_id)).status == "failed"


async def test_abandon_charges_the_estimate_in_one_statement(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 300, 1000, clock)
    other = await env.reserve_call(row_id, workspace, 100, 1000, clock)

    statements: list[str] = []

    def capture(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    sync_engine = env.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture)
    try:
        abandoned = await env.abandon(call, clock)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture)
    assert abandoned is True
    touching = [s for s in statements if "ai_usage_records" in s or "ai_budget_periods" in s]
    assert len(touching) == 1, "abandon must be exactly one statement"

    record = await env.record(call.record_id)
    assert record.status == "abandoned"
    assert record.cost_micro_usd == record.reserved_micro_usd == 300
    assert record.finished_at == clock.now()
    row = await env.row(row_id)
    assert (row.spent_micro_usd, row.reserved_micro_usd) == (300, 100)  # `other` still reserved
    assert (await env.record(other.record_id)).status == "reserved"


async def test_abandon_and_settle_are_noops_after_the_other(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)

    settled = await env.reserve_call(row_id, workspace, 200, 1000, clock)
    await env.settle_call(settled, 150, 1000, clock)
    before = await env.row(row_id)
    assert await env.abandon(settled, clock) is False
    assert await env.row(row_id) == before
    assert (await env.record(settled.record_id)).status == "succeeded"

    abandoned = await env.reserve_call(row_id, workspace, 100, 1000, clock)
    assert await env.abandon(abandoned, clock) is True
    before = await env.row(row_id)
    result = await env.settle_call(abandoned, 10, 1000, clock)
    assert result == repo.SettleResult(flipped=False, warning_newly_set=False)
    assert await env.row(row_id) == before
    assert (await env.record(abandoned.record_id)).cost_micro_usd == 100

    assert await env.abandon(abandoned, clock) is False  # abandoning twice
    assert await env.row(row_id) == before


async def test_abandon_of_an_unknown_record_changes_nothing(env: Env) -> None:
    clock = env.clock()
    row_id = await env.ensure(await env.new_workspace(), clock, 1000)
    before = await env.row(row_id)
    assert await env.abandon(Call(_new_id(), _new_id(), row_id, 1), clock) is False
    assert await env.row(row_id) == before


async def test_abandon_works_for_system_scope(env: Env) -> None:
    clock = env.clock()
    row_id = await env.ensure(None, clock, 1000)
    call = await env.reserve_call(row_id, None, 250, 1000, clock)
    assert await env.abandon(call, clock) is True
    row = await env.row(row_id)
    assert (row.spent_micro_usd, row.reserved_micro_usd) == (250, 0)


async def test_concurrent_settle_and_abandon_exactly_one_wins(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 100_000)
    expected_spent = 0
    for _ in range(8):
        call = await env.reserve_call(row_id, workspace, 100, 100_000, clock)

        async def work(session: AsyncSession, index: int, call: Call = call) -> bool:
            if index == 0:
                result = await repo.settle(
                    session, call.record_id, "succeeded", 1, 1, 40, None, "stop", True, 0, [], 5,
                    call.row_id, call.estimate, 100_000, clock.now(),
                )  # fmt: skip
                return result.flipped
            return await repo.abandon_usage_record(session, call.record_id, clock.now())

        settle_won, abandon_won = await env.concurrently(2, work)
        assert settle_won != abandon_won  # exactly one winner
        record = await env.record(call.record_id)
        expected_spent += 40 if settle_won else 100
        assert record.status == ("succeeded" if settle_won else "abandoned")
        assert record.cost_micro_usd == (40 if settle_won else 100)
        row = await env.row(row_id)
        assert (row.spent_micro_usd, row.reserved_micro_usd) == (expected_spent, 0)
    async with env.sessions() as session, session.begin():
        assert await repo.reconciliation_query(session, [row_id]) == []


# --------------------------------------------------------------------------------------------
# AC-36 / INV-13
# --------------------------------------------------------------------------------------------


async def test_mixed_workload_reconciles(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    limit = 10_000
    workspace_row = await env.ensure(workspace, clock, limit)
    system_row = await env.ensure(None, clock, limit)

    below = await env.reserve_call(workspace_row, workspace, 500, limit, clock)
    above = await env.reserve_call(workspace_row, workspace, 500, limit, clock)
    free = await env.reserve_call(workspace_row, workspace, 300, limit, clock)
    charged_failure = await env.reserve_call(workspace_row, workspace, 300, limit, clock)
    reaped = await env.reserve_call(workspace_row, workspace, 400, limit, clock)
    await env.settle_call(below, 480, limit, clock)
    await env.settle_call(above, 520, limit, clock)  # cost above the estimate: recorded in full
    await env.settle_call(free, 0, limit, clock, outcome="failed")
    await env.settle_call(charged_failure, 120, limit, clock, outcome="failed")
    assert await env.abandon(reaped, clock) is True
    async with env.sessions() as session, session.begin():  # a refusal writes no usage record
        assert await repo.reserve(session, workspace_row, limit * 10, limit, clock.now()) is False
        await repo.record_refusal(session, workspace_row, limit, clock.now())

    sys_ok = await env.reserve_call(system_row, None, 200, limit, clock)
    sys_reaped = await env.reserve_call(system_row, None, 100, limit, clock)
    await env.settle_call(sys_ok, 200, limit, clock)
    await env.abandon(sys_reaped, clock)

    period = repo.period_start_for(clock.now())
    async with env.sessions() as session, session.begin():
        assert await repo.reconciliation_query(session, [workspace_row, system_row]) == []
    for row_id, owner, expected in ((workspace_row, workspace, 1520), (system_row, None, 300)):
        row = await env.row(row_id)
        assert row.reserved_micro_usd == 0
        assert row.spent_micro_usd == expected
        assert await env.ledger_sum(owner, period) == row.spent_micro_usd


async def test_reconciliation_query_reports_a_mismatch_and_never_repairs(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 100, 1000, clock)
    await env.settle_call(call, 100, 1000, clock)

    async with env.sessions() as session, session.begin():  # corrupt the counter on purpose
        await session.execute(
            text(
                "UPDATE ai_budget_periods SET spent_micro_usd = spent_micro_usd + 7 "
                "WHERE id = :i"
            ),
            {"i": row_id},
        )
    async with env.sessions() as session, session.begin():
        mismatches = await repo.reconciliation_query(session, [row_id])
    assert [(m.budget_row_id, m.spent_micro_usd, m.ledger_cost_micro_usd) for m in mismatches] == [
        (row_id, 107, 100)
    ]
    assert (await env.row(row_id)).spent_micro_usd == 107  # reads only

    # A row that still has reservations in flight is not judged.
    await env.reserve_call(row_id, workspace, 50, 1000, clock, attempt_no=1)
    async with env.sessions() as session, session.begin():
        assert await repo.reconciliation_query(session, [row_id]) == []


# --------------------------------------------------------------------------------------------
# Constraint safety
# --------------------------------------------------------------------------------------------


async def test_settle_budget_never_lets_reserved_go_negative(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    await env.reserve_call(row_id, workspace, 100, 1000, clock)
    before = await env.row(row_id)

    async with env.sessions() as session:
        async with session.begin():
            with pytest.raises(repo.BudgetRepositoryError):  # not IntegrityError
                await repo.settle_budget(session, row_id, 101, 5, 1000, clock.now())
    assert await env.row(row_id) == before

    async with env.sessions() as session, session.begin():
        with pytest.raises(repo.BudgetRepositoryError):
            await repo.settle_budget(session, _new_id(), 1, 1, 1000, clock.now())


async def test_settle_rejects_an_estimate_that_differs_from_the_record(env: Env) -> None:
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    call = await env.reserve_call(row_id, workspace, 100, 1000, clock)
    async with env.sessions() as session:
        with pytest.raises(repo.BudgetRepositoryError):
            async with session.begin():
                await repo.settle(
                    session, call.record_id, "succeeded", 1, 1, 10, None, "stop", True, 0, [], 5,
                    row_id, 99, 1000, clock.now(),
                )  # fmt: skip
    # the caller's rollback left everything as it was
    assert (await env.record(call.record_id)).status == "reserved"
    assert (await env.row(row_id)).reserved_micro_usd == 100


async def test_usage_check_constraint_still_guards_the_schema(env: Env) -> None:
    """Sanity: the database, not this module, is the last line of defence."""
    clock = env.clock()
    workspace = await env.new_workspace()
    row_id = await env.ensure(workspace, clock, 1000)
    async with env.sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(
                    text("UPDATE ai_budget_periods SET reserved_micro_usd = -1 WHERE id = :i"),
                    {"i": row_id},
                )
