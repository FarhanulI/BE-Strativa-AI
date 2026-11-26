"""Shared environment for the committed-session database tests of ai_platform step 5b-1.

Same pattern as ``tests/db/test_budget_coordinator.py``: every test commits real rows through
separate sessions, so none can use the rollback fixture. Each environment owns a private calendar
year (system-scope budget rows have no workspace to cascade from) and records every id it creates.
Teardown deletes ONLY what the test created or caused, by id: the requests (their usage records
cascade), the budget rows, the outbox events and audit rows of those budget rows, and the
workspaces. Nothing is truncated. ``audit_log`` is append-only by a row trigger, so its rows go
through ``tests.helpers.audit_teardown.delete_audit_rows`` (local marker check, trigger re-enabled
and verified, whole transaction rolled back on failure).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as repo
from app.ai_platform.budget_coordinator import BudgetCoordinator, ReservationParams
from app.ai_platform.config import AiPlatformConfig
from app.core import FakeClock, Settings, SystemClock, UUID7Factory
from app.db_migrations.engine import build_async_engine
from app.events_outbox import OutboxEvent
from app.workspace.models import Workspace
from tests.helpers.audit_teardown import delete_audit_rows

POOL = 60


def new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


def _config(workspace_micro: int, system_micro: int) -> AiPlatformConfig:
    return AiPlatformConfig(
        workspace_monthly_budget_usd=f"{Decimal(workspace_micro) / Decimal(1_000_000):.6f}",
        system_monthly_budget_usd=f"{Decimal(system_micro) / Decimal(1_000_000):.6f}",
    )


@dataclass
class AiDbEnv:
    engine: Any
    sessions: async_sessionmaker[AsyncSession]
    year: int
    workspaces: list[UUID] = field(default_factory=list)
    requests: list[UUID] = field(default_factory=list)
    budget_rows: list[UUID] = field(default_factory=list)

    # ---- construction helpers -----------------------------------------------------------------

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
            workspace = Workspace(name="req-test", slug=f"req-{new_id()}")
            session.add(workspace)
            await session.flush()
            workspace_id = workspace.id
        self.workspaces.append(workspace_id)
        return workspace_id

    async def raw_request(self, **columns: Any) -> UUID:
        """Insert an ``ai_requests`` row with exactly the given columns (committed)."""
        request_id = columns.pop("id", None) or new_id()
        values = {"id": request_id, **columns}
        names = ", ".join(values)
        placeholders = ", ".join(f":{name}" for name in values)
        self.requests.append(request_id)
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(f"INSERT INTO ai_requests ({names}) VALUES ({placeholders})"), values
            )
        return request_id

    async def sync_request(self, workspace_id: UUID | None, clock: FakeClock) -> UUID:
        """A committed running sync row created the way 3b's tests do (raw SQL, no repository)."""
        system = workspace_id is None
        return await self.raw_request(
            scope="system" if system else "workspace",
            workspace_id=workspace_id,
            actor_type="system" if system else "user",
            task="EMBED_TEXT" if system else "GENERATE_HOOK_VARIATIONS",
            output_schema_name=None if system else "HookVariationSet",
            output_schema_version=None if system else 1,
            mode="sync",
            status="running",
            correlation_request_id="req-test",
            started_at=clock.now(),
        )

    def reservation_params(self, request_id: UUID, workspace_id: UUID | None) -> ReservationParams:
        system = workspace_id is None
        return ReservationParams(
            request_id=request_id,
            attempt_no=1,
            task="EMBED_TEXT" if system else "GENERATE_HOOK_VARIATIONS",
            call_kind="embedding" if system else "generation",
            provider="fakeprov",
            model="fake-chat-zq1",
            catalog_version="test-1",
            price_version="test-prices-1",
            billing_mode="paid",
            routing_version="r1",
            route_rank=1,
            candidate_snapshot=[{"model": "fake-chat-zq1", "eligible": True, "reason_code": None}],
        )

    async def reserve(
        self,
        coordinator: BudgetCoordinator,
        workspace_id: UUID | None,
        clock: FakeClock,
        estimate: int,
    ) -> UUID:
        """Reserve once through the coordinator; returns the budget row id."""
        request_id = await self.sync_request(workspace_id, clock)
        scope: repo.Scope = "system" if workspace_id is None else "workspace"
        result = await coordinator.reserve_for_call(
            scope, workspace_id, estimate, self.reservation_params(request_id, workspace_id)
        )
        if result.budget_row_id not in self.budget_rows:
            self.budget_rows.append(result.budget_row_id)
        return result.budget_row_id

    async def add_usage(
        self,
        request_id: UUID,
        attempt_no: int,
        clock: FakeClock,
        *,
        status: str,
        input_units: int | None,
        output_units: int | None,
        cost_micro_usd: int,
        reserved_micro_usd: int,
        scope: str = "workspace",
        workspace_id: UUID | None = None,
    ) -> UUID:
        """Insert one usage row directly (committed). ``finished_at`` is set unless reserved."""
        record_id = new_id()
        started = clock.now()
        async with self.sessions() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO ai_usage_records (id, request_id, attempt_no, scope, "
                    "workspace_id, task, call_kind, provider, model, catalog_version, "
                    "price_version, billing_mode, routing_version, route_rank, "
                    "candidate_snapshot, status, input_units, output_units, "
                    "reserved_micro_usd, cost_micro_usd, period_start, started_at, "
                    "finished_at) VALUES (:id, :request_id, :attempt_no, :scope, "
                    ":workspace_id, 'GENERATE_HOOK_VARIATIONS', 'generation', 'fakeprov', "
                    "'fake-chat-zq1', 'test-1', 'test-prices-1', 'paid', 'r1', 1, "
                    "CAST(:snapshot AS jsonb), :status, :input_units, :output_units, "
                    ":reserved, :cost, :period, :started, :finished)"
                ),
                {
                    "id": record_id,
                    "request_id": request_id,
                    "attempt_no": attempt_no,
                    "scope": scope,
                    "workspace_id": workspace_id,
                    "snapshot": json.dumps([]),
                    "status": status,
                    "input_units": input_units,
                    "output_units": output_units,
                    "reserved": reserved_micro_usd,
                    "cost": cost_micro_usd,
                    "period": repo.period_start_for(started),
                    "started": started,
                    "finished": None if status == "reserved" else started,
                },
            )
        return record_id

    # ---- reads --------------------------------------------------------------------------------

    async def request_row(self, request_id: UUID) -> Any:
        async with self.sessions() as session, session.begin():
            return (
                await session.execute(
                    text("SELECT * FROM ai_requests WHERE id = :id"), {"id": request_id}
                )
            ).one()

    async def count_requests(self, ids: list[UUID]) -> int:
        async with self.sessions() as session, session.begin():
            return int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM ai_requests WHERE id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": ids},
                    )
                ).scalar_one()
            )

    async def independent_sums(self, request_id: UUID) -> tuple[int, int, int]:
        """SUM over the request's settled usage rows, written separately from the repository."""
        async with self.sessions() as session, session.begin():
            row = (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(COALESCE(input_units, 0)), 0), "
                        "COALESCE(SUM(COALESCE(output_units, 0)), 0), "
                        "COALESCE(SUM(cost_micro_usd), 0) FROM ai_usage_records "
                        "WHERE request_id = :id AND status <> 'reserved'"
                    ),
                    {"id": request_id},
                )
            ).one()
        return int(row[0]), int(row[1]), int(row[2])

    async def find_budget_row(self, workspace_id: UUID | None, clock: FakeClock) -> UUID | None:
        period = repo.period_start_for(clock.now())
        async with self.sessions() as session, session.begin():
            found = await session.execute(
                text(
                    "SELECT id FROM ai_budget_periods WHERE scope = :scope "
                    "AND workspace_id IS NOT DISTINCT FROM :w AND period_start = :period"
                ),
                {
                    "scope": "system" if workspace_id is None else "workspace",
                    "w": workspace_id,
                    "period": period,
                },
            )
            row_id = found.scalar_one_or_none()
        if row_id is not None and row_id not in self.budget_rows:
            self.budget_rows.append(row_id)
        return row_id

    async def budget_row(self, row_id: UUID) -> repo.BudgetRowSnapshot:
        async with self.sessions() as session, session.begin():
            snapshot = await repo.get_budget_row(session, row_id)
        assert snapshot is not None
        return snapshot

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
                    "payload FROM outbox_events WHERE aggregate_id = :id "
                    "ORDER BY created_at, event_id"
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

    # ---- teardown -----------------------------------------------------------------------------

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


def build_env(settings: Settings) -> AiDbEnv:
    engine = build_async_engine(
        settings.require_database_url(direct=True),
        pooled=False,
        engine_options={"pool_size": POOL, "max_overflow": 0},
    )
    return AiDbEnv(
        engine=engine,
        sessions=async_sessionmaker(engine, expire_on_commit=False),
        year=2200 + secrets.randbelow(2000),
    )
