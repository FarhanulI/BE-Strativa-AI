"""Database tests for the BudgetCoordinator (ai_platform step 3b).

Covers AC-31 (event part), AC-34, AC-35, AC-52 (privacy part, budget path only), INV-15, INV-18.
Not covered here: AC-58 (needs the request-row fence), lease, reaper, request events.

Isolation: every test commits real rows through separate sessions, so none can use the rollback
fixture. Each test builds its own workspaces and requests with fresh ids and a private calendar year
(system-scope budget rows have no workspace to cascade from). Teardown deletes ONLY what the test
created or caused, by id: the usage records (through their request), the budget rows, the outbox
events and audit rows of those budget rows, and the workspaces. Nothing is truncated. ``audit_log``
is append-only by a row trigger, so the teardown goes through ``tests.helpers.audit_teardown``: it
refuses on a database without the local marker, disables that one trigger inside its own
transaction, deletes the audit rows by id, enables it again and verifies it in pg_trigger; a
failure rolls the whole transaction back, so the trigger is never left disabled.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from structlog.testing import capture_logs

from app.ai_platform import budget_coordinator as coordinator_module
from app.ai_platform import budget_repository as repo
from app.ai_platform.budget_coordinator import (
    BudgetCoordinator,
    ReservationParams,
    ReservationResult,
    SettlementOutcome,
)
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.errors import AiBudgetExceeded
from app.core import FakeClock, Settings, SystemClock, UUID7Factory
from app.db_migrations.engine import build_async_engine
from app.events_outbox import DomainEvent, OutboxEvent
from app.workspace.models import Workspace
from tests.helpers.audit_teardown import delete_audit_rows

pytestmark = pytest.mark.db

POOL = 60
TIMEOUT_SECONDS = 60
SENTINEL = "zq9-sentinel-provider-7f3a"
MODEL_SENTINEL = "zq9-sentinel-model-1c2d"

EVENT_KEYS = {
    "scope",
    "period_start",
    "threshold_percent",
    "limit_micro_usd",
    "spent_micro_usd",
    "reserved_micro_usd",
}
AUDIT_KEYS = EVENT_KEYS | {"budget_row_id"}
LOG_KEYS = {
    "event",
    "log_level",
    "scope",
    "task",
    "period",
    "workspace_id",
    "limit_micro_usd",
    "spent_micro_usd",
}


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


def _config(workspace_micro: int, system_micro: int) -> AiPlatformConfig:
    return AiPlatformConfig(
        workspace_monthly_budget_usd=f"{Decimal(workspace_micro) / Decimal(1_000_000):.6f}",
        system_monthly_budget_usd=f"{Decimal(system_micro) / Decimal(1_000_000):.6f}",
    )


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

    def coordinator(
        self,
        clock: FakeClock,
        limit: int,
        publish_event: Callable[..., Awaitable[OutboxEvent]] | None = None,
        system_limit: int | None = None,
    ) -> BudgetCoordinator:
        config = _config(limit, limit if system_limit is None else system_limit)
        if publish_event is None:
            return BudgetCoordinator(self.sessions, clock, config)
        return BudgetCoordinator(self.sessions, clock, config, publish_event)

    async def new_workspace(self) -> UUID:
        async with self.sessions() as session, session.begin():
            workspace = Workspace(name="coord-test", slug=f"coord-{_new_id()}")
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

    def params(
        self,
        request_id: UUID,
        workspace_id: UUID | None,
        provider: str = "fakeprov",
        model: str = "fake-chat-zq1",
    ) -> ReservationParams:
        system = workspace_id is None
        return ReservationParams(
            request_id=request_id,
            attempt_no=1,
            task="EMBED_TEXT" if system else "GENERATE_HOOK_VARIATIONS",
            call_kind="embedding" if system else "generation",
            provider=provider,
            model=model,
            catalog_version="test-1",
            price_version="test-prices-1",
            billing_mode="paid",
            routing_version="r1",
            route_rank=1,
            candidate_snapshot=[{"model": model, "eligible": True, "reason_code": None}],
        )

    async def reserve(
        self,
        coordinator: BudgetCoordinator,
        workspace_id: UUID | None,
        clock: FakeClock,
        estimate: int,
        provider: str = "fakeprov",
        model: str = "fake-chat-zq1",
    ) -> ReservationResult:
        request_id = await self.new_request(workspace_id, clock)
        scope: repo.Scope = "system" if workspace_id is None else "workspace"
        result = await coordinator.reserve_for_call(
            scope, workspace_id, estimate, self.params(request_id, workspace_id, provider, model)
        )
        if result.budget_row_id not in self.budget_rows:
            self.budget_rows.append(result.budget_row_id)
        return result

    async def settle(
        self,
        coordinator: BudgetCoordinator,
        result: ReservationResult,
        scope: str,
        estimate: int,
        cost: int,
    ) -> repo.SettleResult:
        return await coordinator.settle_call(
            result.usage_record_id,
            result.budget_row_id,
            estimate,
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

    async def find_row(self, workspace_id: UUID | None, clock: FakeClock) -> UUID:
        period = repo.period_start_for(clock.now())
        async with self.sessions() as session, session.begin():
            if workspace_id is None:
                found = await session.execute(
                    text(
                        "SELECT id FROM ai_budget_periods "
                        "WHERE scope = 'system' AND period_start = :period"
                    ),
                    {"period": period},
                )
            else:
                found = await session.execute(
                    text(
                        "SELECT id FROM ai_budget_periods "
                        "WHERE scope = 'workspace' AND workspace_id = :w AND period_start = :period"
                    ),
                    {"w": workspace_id, "period": period},
                )
            row_id = found.scalar_one()
        if row_id not in self.budget_rows:
            self.budget_rows.append(row_id)
        return row_id

    async def count_budget_rows(self, scope: str, workspace_id: UUID | None, period: date) -> int:
        async with self.sessions() as session, session.begin():
            return int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM ai_budget_periods WHERE scope = :scope "
                            "AND workspace_id IS NOT DISTINCT FROM :w AND period_start = :period"
                        ),
                        {"scope": scope, "w": workspace_id, "period": period},
                    )
                ).scalar_one()
            )

    async def row(self, row_id: UUID) -> repo.BudgetRowSnapshot:
        async with self.sessions() as session, session.begin():
            snapshot = await repo.get_budget_row(session, row_id)
        assert snapshot is not None
        return snapshot

    async def usage(self, record_id: UUID) -> Any:
        async with self.sessions() as session, session.begin():
            return (
                await session.execute(
                    text(
                        "SELECT status, cost_micro_usd, reserved_micro_usd "
                        "FROM ai_usage_records WHERE id = :id"
                    ),
                    {"id": record_id},
                )
            ).one()

    async def usage_count(self) -> int:
        async with self.sessions() as session, session.begin():
            return int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM ai_usage_records "
                            "WHERE request_id = ANY(CAST(:r AS uuid[]))"
                        ),
                        {"r": self.requests},
                    )
                ).scalar_one()
            )

    async def events(self, row_id: UUID) -> list[Any]:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "SELECT event_id, event_type, event_version, aggregate_type, workspace_id, "
                    "payload FROM outbox_events WHERE aggregate_id = :id ORDER BY created_at, "
                    "event_id"
                ),
                {"id": row_id},
            )
            return list(result.all())

    async def audits(self, row_id: UUID) -> list[Any]:
        async with self.sessions() as session, session.begin():
            result = await session.execute(
                text(
                    "SELECT action, actor_type, workspace_id, resource_type, resource_id, "
                    "event_id, details FROM audit_log "
                    "WHERE resource_type = 'ai_budget' AND resource_id = :id ORDER BY occurred_at"
                ),
                {"id": str(row_id)},
            )
            return list(result.all())

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


async def _gather(*awaitables: Awaitable[Any]) -> list[Any]:
    async with asyncio.timeout(TIMEOUT_SECONDS):
        return list(await asyncio.gather(*awaitables, return_exceptions=True))


SCOPES: list[repo.Scope] = ["workspace", "system"]


async def _workspace_for(env: Env, scope: repo.Scope) -> UUID | None:
    return await env.new_workspace() if scope == "workspace" else None


# --------------------------------------------------------------------------------------------
# AC-35 / INV-15: refusal
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
async def test_refusal_publishes_exactly_one_exhausted_event_and_audit(
    env: Env, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, 1_000)
    first = await env.reserve(coordinator, workspace_id, clock, 600)  # remaining 400 < 600

    request_id = await env.new_request(workspace_id, clock)
    with pytest.raises(AiBudgetExceeded):
        await coordinator.reserve_for_call(
            scope,
            workspace_id,
            600,
            env.params(request_id, workspace_id),
        )

    # The call raised, yet its event and audit record are already committed and visible.
    row_id = first.budget_row_id
    events = await env.events(row_id)
    audits = await env.audits(row_id)
    assert len(events) == 1 and len(audits) == 1
    event, audit = events[0], audits[0]
    assert event.event_type == "ai.budget_exhausted" and event.event_version == 1
    assert event.aggregate_type == "ai_budget"
    assert event.workspace_id == workspace_id
    payload = event.payload
    assert set(payload) == EVENT_KEYS
    assert payload["scope"] == scope
    assert payload["threshold_percent"] == 100
    assert payload["period_start"] == repo.period_start_for(clock.now()).isoformat()
    assert payload["limit_micro_usd"] == 1_000
    assert payload["spent_micro_usd"] == 0
    assert payload["spent_micro_usd"] < payload["limit_micro_usd"]
    assert payload["reserved_micro_usd"] == 600
    assert audit.action == "ai.budget.exhausted" and audit.actor_type == "system"
    assert audit.resource_type == "ai_budget" and audit.resource_id == str(row_id)
    assert audit.workspace_id == workspace_id
    assert audit.event_id == event.event_id
    assert set(audit.details) == AUDIT_KEYS
    assert audit.details["budget_row_id"] == str(row_id)

    # No usage row for the refused call, and nothing reserved for it.
    assert await env.usage_count() == 1
    snapshot = await env.row(row_id)
    assert snapshot.reserved_micro_usd == 600 and snapshot.spent_micro_usd == 0
    assert snapshot.exhausted_notified_at is not None

    # A second refusal and many concurrent refusals add nothing.
    for _ in range(2):
        with pytest.raises(AiBudgetExceeded):
            await coordinator.reserve_for_call(
                scope,
                workspace_id,
                600,
                env.params(request_id, workspace_id),
            )
    outcomes = await _gather(
        *(
            coordinator.reserve_for_call(
                scope,
                workspace_id,
                600,
                env.params(request_id, workspace_id),
            )
            for _ in range(25)
        )
    )
    assert all(isinstance(item, AiBudgetExceeded) for item in outcomes)
    assert len(await env.events(row_id)) == 1
    assert len(await env.audits(row_id)) == 1
    assert await env.usage_count() == 1
    assert (await env.row(row_id)).reserved_micro_usd == 600


@pytest.mark.parametrize("scope", SCOPES)
async def test_concurrent_first_refusals_publish_once(env: Env, scope: repo.Scope) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, 500)
    first = await env.reserve(coordinator, workspace_id, clock, 500)  # row is now full
    request_id = await env.new_request(workspace_id, clock)
    outcomes = await _gather(
        *(
            coordinator.reserve_for_call(
                scope,
                workspace_id,
                1,
                env.params(request_id, workspace_id),
            )
            for _ in range(30)
        )
    )
    assert all(isinstance(item, AiBudgetExceeded) for item in outcomes)
    assert len(await env.events(first.budget_row_id)) == 1
    assert len(await env.audits(first.budget_row_id)) == 1


# --------------------------------------------------------------------------------------------
# AC-34 / INV-15: 80 % threshold
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
async def test_threshold_is_published_by_the_settlement_that_crosses_it(
    env: Env, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, 1_000)
    calls = [await env.reserve(coordinator, workspace_id, clock, 100) for _ in range(8)]
    row_id = calls[0].budget_row_id

    # Reservations alone (800 reserved of 1000, nothing settled) publish nothing.
    assert await env.events(row_id) == [] and await env.audits(row_id) == []

    for call in calls[:7]:
        result = await env.settle(coordinator, call, scope, 100, 100)
        assert result.flipped and not result.warning_newly_set
    assert await env.events(row_id) == []  # settled spent is 700, below 80 %

    crossing = await env.settle(coordinator, calls[7], scope, 100, 100)  # settled spent 800
    assert crossing.warning_newly_set
    events, audits = await env.events(row_id), await env.audits(row_id)
    assert len(events) == 1 and len(audits) == 1
    event, audit = events[0], audits[0]
    assert event.event_type == "ai.budget_threshold_reached"
    assert event.workspace_id == workspace_id
    assert set(event.payload) == EVENT_KEYS
    assert event.payload["threshold_percent"] == 80
    assert event.payload["spent_micro_usd"] == 800
    assert event.payload["reserved_micro_usd"] == 0
    assert event.payload["limit_micro_usd"] == 1_000
    assert audit.action == "ai.budget.threshold_reached" and audit.actor_type == "system"
    assert audit.event_id == event.event_id
    assert audit.workspace_id == workspace_id

    # Calls continue, and nothing further is published.
    more = await env.reserve(coordinator, workspace_id, clock, 100)
    again = await env.settle(coordinator, more, scope, 100, 100)
    assert again.flipped and not again.warning_newly_set
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1


@pytest.mark.parametrize("scope", SCOPES)
async def test_concurrent_crossing_settlements_publish_once(env: Env, scope: repo.Scope) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, 2_000)
    calls = [await env.reserve(coordinator, workspace_id, clock, 100) for _ in range(18)]
    row_id = calls[0].budget_row_id
    assert await env.events(row_id) == []  # 1800 reserved, nothing settled

    results = await _gather(*(env.settle(coordinator, call, scope, 100, 100) for call in calls))
    assert all(isinstance(item, repo.SettleResult) for item in results), results
    assert sum(1 for item in results if item.warning_newly_set) == 1
    assert len(await env.events(row_id)) == 1
    assert len(await env.audits(row_id)) == 1
    snapshot = await env.row(row_id)
    assert snapshot.spent_micro_usd == 1_800 and snapshot.reserved_micro_usd == 0

    extra = await env.reserve(coordinator, workspace_id, clock, 100)  # calls continue
    assert extra.usage_record_id is not None


# --------------------------------------------------------------------------------------------
# Rollback behaviour of the settlement transaction
# --------------------------------------------------------------------------------------------


async def _failing_publish(session: AsyncSession, event: DomainEvent) -> OutboxEvent:
    raise RuntimeError("publishing is down")


async def _failing_audit(session: AsyncSession, record: Any) -> Any:
    raise RuntimeError("audit append is down")


@pytest.mark.parametrize("failure", ["publish", "audit"])
async def test_failed_publish_or_audit_rolls_the_settlement_back(
    env: Env, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    good = env.coordinator(clock, 1_000)
    calls = [await env.reserve(good, workspace_id, clock, 100) for _ in range(8)]
    row_id = calls[0].budget_row_id
    for call in calls[:7]:
        await env.settle(good, call, "workspace", 100, 100)
    before = await env.row(row_id)
    assert before.spent_micro_usd == 700 and before.reserved_micro_usd == 100

    if failure == "publish":
        broken = env.coordinator(clock, 1_000, publish_event=_failing_publish)
    else:
        broken = env.coordinator(clock, 1_000)
        monkeypatch.setattr(coordinator_module, "append_audit", _failing_audit)
    with pytest.raises(RuntimeError):
        await env.settle(broken, calls[7], "workspace", 100, 100)
    monkeypatch.undo()

    record = await env.usage(calls[7].usage_record_id)
    assert record.status == "reserved" and record.cost_micro_usd == 0
    after = await env.row(row_id)
    assert after.spent_micro_usd == 700 and after.reserved_micro_usd == 100
    assert after.warning_notified_at is None
    assert await env.events(row_id) == [] and await env.audits(row_id) == []

    retry = await env.settle(good, calls[7], "workspace", 100, 100)
    assert retry.flipped and retry.warning_newly_set
    assert (await env.usage(calls[7].usage_record_id)).status == "succeeded"
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1
    assert (await env.row(row_id)).warning_notified_at is not None


async def test_double_settlement_is_a_noop_and_publishes_nothing_more(env: Env) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock, 100)
    call = await env.reserve(coordinator, workspace_id, clock, 90)
    first = await env.settle(coordinator, call, "workspace", 90, 90)
    second = await env.settle(coordinator, call, "workspace", 90, 90)
    assert first.flipped and first.warning_newly_set
    assert not second.flipped and not second.warning_newly_set
    assert len(await env.events(call.budget_row_id)) == 1


# --------------------------------------------------------------------------------------------
# AC-31 (event part): scope and workspace of the events
# --------------------------------------------------------------------------------------------


async def test_workspace_events_carry_the_workspace_and_never_touch_the_system_row(
    env: Env,
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock, 1_000, system_limit=1_000)
    call = await env.reserve(coordinator, workspace_id, clock, 800)
    await env.settle(coordinator, call, "workspace", 800, 800)  # warning
    with pytest.raises(AiBudgetExceeded):
        await env.reserve(coordinator, workspace_id, clock, 300)  # refusal

    row_id = call.budget_row_id
    events = await env.events(row_id)
    assert {event.event_type for event in events} == {
        "ai.budget_threshold_reached",
        "ai.budget_exhausted",
    }
    assert all(event.workspace_id == workspace_id for event in events)
    assert all(event.payload["scope"] == "workspace" for event in events)
    assert all(audit.workspace_id == workspace_id for audit in await env.audits(row_id))
    period = repo.period_start_for(clock.now())
    assert await env.count_budget_rows("system", None, period) == 0


async def test_system_events_have_no_workspace(env: Env) -> None:
    clock = env.clock()
    coordinator = env.coordinator(clock, 1_000)
    call = await env.reserve(coordinator, None, clock, 800)
    await env.settle(coordinator, call, "system", 800, 800)
    with pytest.raises(AiBudgetExceeded):
        await env.reserve(coordinator, None, clock, 300)
    events = await env.events(call.budget_row_id)
    assert len(events) == 2
    assert all(event.workspace_id is None for event in events)
    assert all(event.payload["scope"] == "system" for event in events)
    assert all(audit.workspace_id is None for audit in await env.audits(call.budget_row_id))


# --------------------------------------------------------------------------------------------
# Reservation path
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
async def test_reservation_is_committed_and_uses_the_current_limit(
    env: Env, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    result = await env.reserve(env.coordinator(clock, 1_000), workspace_id, clock, 250)

    # Visible to a second session as soon as the call returned: it is committed.
    record = await env.usage(result.usage_record_id)
    assert record.status == "reserved" and record.reserved_micro_usd == 250
    snapshot = await env.row(result.budget_row_id)
    assert snapshot.reserved_micro_usd == 250 and snapshot.spent_micro_usd == 0
    assert result.limit_micro_usd == 1_000 == snapshot.limit_micro_usd

    # A configuration change applies to the next reservation at once.
    raised = await env.reserve(env.coordinator(clock, 5_000), workspace_id, clock, 250)
    assert raised.limit_micro_usd == 5_000
    assert (await env.row(result.budget_row_id)).limit_micro_usd == 5_000
    assert await env.events(result.budget_row_id) == []  # a reservation alone publishes nothing


# --------------------------------------------------------------------------------------------
# Concurrency sanity
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
async def test_concurrent_reservations_admit_exactly_k(env: Env, scope: repo.Scope) -> None:
    k, n, estimate = 7, 30, 100
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, k * estimate)
    request_ids = [await env.new_request(workspace_id, clock) for _ in range(n)]
    outcomes = await _gather(
        *(
            coordinator.reserve_for_call(
                scope,
                workspace_id,
                estimate,
                env.params(request_id, workspace_id),
            )
            for request_id in request_ids
        )
    )
    admitted = [item for item in outcomes if isinstance(item, ReservationResult)]
    refused = [item for item in outcomes if isinstance(item, AiBudgetExceeded)]
    assert len(admitted) == k and len(refused) == n - k, outcomes
    row_id = await env.find_row(workspace_id, clock)
    snapshot = await env.row(row_id)
    assert snapshot.reserved_micro_usd == k * estimate and snapshot.spent_micro_usd == 0
    assert await env.usage_count() == k
    assert len(await env.events(row_id)) == 1  # at most one exhausted event
    assert len(await env.audits(row_id)) == 1


# --------------------------------------------------------------------------------------------
# AC-52 (privacy part, budget path only)
# --------------------------------------------------------------------------------------------


async def test_logs_events_and_audit_carry_only_ids_codes_and_amounts(env: Env) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock, 1_000)

    with capture_logs() as logs:
        # Sentinels only in the provider and model fields, where the usage record legitimately
        # holds them. They must not reach logs, events or audit details.
        call = await env.reserve(
            coordinator, workspace_id, clock, 800, provider=SENTINEL, model=MODEL_SENTINEL
        )
        await env.settle(coordinator, call, "workspace", 800, 800)  # warning
        with pytest.raises(AiBudgetExceeded):
            await env.reserve(
                coordinator, workspace_id, clock, 300, provider=SENTINEL, model=MODEL_SENTINEL
            )

    row_id = call.budget_row_id
    events, audits = await env.events(row_id), await env.audits(row_id)
    assert len(events) == 2 and len(audits) == 2
    assert {entry["event"] for entry in logs} == {"ai_budget_threshold", "ai_budget_refused"}

    for entry in logs:
        assert set(entry) <= LOG_KEYS, entry
        for value in entry.values():
            assert isinstance(value, (str, int)) and not isinstance(value, bool)
    for event in events:
        assert set(event.payload) == EVENT_KEYS
        assert all(isinstance(value, (str, int)) for value in event.payload.values())
    for audit in audits:
        assert set(audit.details) == AUDIT_KEYS
        assert all(isinstance(value, (str, int)) for value in audit.details.values())

    everything = json.dumps(
        {
            "logs": logs,
            "events": [dict(event.payload) for event in events],
            "audits": [dict(audit.details) for audit in audits],
        },
        default=str,
    ).lower()
    assert SENTINEL not in everything and MODEL_SENTINEL not in everything
    assert "token" not in everything
    assert "prompt" not in everything and "completion" not in everything
