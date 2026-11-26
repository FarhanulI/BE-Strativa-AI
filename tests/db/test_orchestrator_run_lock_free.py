"""T-011 step 8: no provider call runs inside a database transaction (local Postgres).

Covers AC-38 (``run`` part: the first call, a repair call and a fallback call) and INV-6.
The provider is a spy over the scripted fake. At the moment each provider call starts, the spy uses
a SEPARATE connection to check, for the request's rows, that:

* ``SELECT ... FOR UPDATE NOWAIT`` succeeds on the ``ai_requests``, ``ai_usage_records`` and
  ``ai_budget_periods`` rows (no row lock is held by the orchestrator), and
* ``pg_stat_activity`` shows no connection of the orchestrator (it has its own engine and a unique
  ``application_name``) with an open transaction (``xact_start`` set, or ``idle in transaction``).

It also checks that the in-flight usage row is already committed as ``reserved`` (visible to
another connection) and that the request row is ``running``. A control test proves the probe
detects a held row lock and an open transaction, so a clean result is not a blind spot.
Synthetic text only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import (
    AiCallContext,
    AiTaskName,
    AiTaskRequest,
    FakeAiProvider,
    ScriptedResponse,
)
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.provider import ProviderGenerationRequest, ProviderGenerationResponse
from app.core import Settings
from app.db_migrations.engine import build_async_engine
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
APP_NAME = "t011-step8-orchestrator"
LOCK_NOT_AVAILABLE = "55P03"
TABLES = ("ai_requests", "ai_usage_records", "ai_budget_periods")
ENTRIES = tuple(
    chat_entry(provider=CHAT_PROVIDER, model=f"synthetic-{name}", latency_p50_ms=500 + 100 * index)
    for index, name in enumerate("abc")
)
BAD = json.dumps({"value": 5})


@dataclass(frozen=True)
class Observation:
    """What a separate connection saw at the start of one provider call."""

    locked: tuple[str, ...]
    row_counts: dict[str, int]
    usage_statuses: tuple[str, ...]
    request_status: str
    open_transactions: tuple[tuple[str, bool], ...]  # (state, has xact_start) of the orchestrator


def _sqlstate(error: DBAPIError) -> str | None:
    orig: Any = error.orig
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


async def probe(env: AiDbEnv, workspace_id: UUID) -> Observation:
    locked: list[str] = []
    counts: dict[str, int] = {}
    async with env.sessions() as session, session.begin():
        for table in TABLES:
            try:
                async with session.begin_nested():
                    found = await session.execute(
                        text(f"SELECT id FROM {table} WHERE workspace_id = :w FOR UPDATE NOWAIT"),
                        {"w": workspace_id},
                    )
                    counts[table] = len(found.all())
            except DBAPIError as error:
                if _sqlstate(error) != LOCK_NOT_AVAILABLE:
                    raise
                locked.append(table)
        statuses = (
            await session.execute(
                text(
                    "SELECT status FROM ai_usage_records WHERE workspace_id = :w "
                    "ORDER BY attempt_no"
                ),
                {"w": workspace_id},
            )
        ).scalars()
        usage_statuses = tuple(statuses)
        request_status = (
            await session.execute(
                text("SELECT status FROM ai_requests WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
        ).scalar_one()
        activity = (
            await session.execute(
                text(
                    "SELECT state, xact_start IS NOT NULL FROM pg_stat_activity "
                    "WHERE application_name = :n AND pid <> pg_backend_pid()"
                ),
                {"n": APP_NAME},
            )
        ).all()
    open_transactions = tuple(
        (str(state), bool(started))
        for state, started in activity
        if started or str(state).startswith("idle in transaction")
    )
    return Observation(
        tuple(locked), counts, usage_statuses, str(request_status), open_transactions
    )


class SpyProvider(FakeAiProvider):
    """Records a database observation at the start of every provider call."""

    def __init__(self, script: list[ScriptedResponse]) -> None:
        super().__init__(script)
        self.observe: Callable[[], Awaitable[Observation]] | None = None
        self.observations: list[Observation] = []

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: SecretStr | None
    ) -> ProviderGenerationResponse:
        assert self.observe is not None
        self.observations.append(await self.observe())
        return await super().generate(request, api_key=api_key)


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[AiDbEnv]:
    environment = build_env(migrated_test_schema)
    try:
        yield environment
    finally:
        try:
            async with environment.sessions() as session, session.begin():
                found = await session.execute(
                    text("SELECT id FROM ai_requests WHERE workspace_id = ANY(CAST(:w AS uuid[]))"),
                    {"w": environment.workspaces},
                )
                for (request_id,) in found.all():
                    if request_id not in environment.requests:
                        environment.requests.append(request_id)
            await environment.cleanup()
        finally:
            await environment.engine.dispose()


@pytest.fixture
async def orchestrator_sessions(
    migrated_test_schema: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The orchestrator's own engine; its connections carry a unique ``application_name``."""
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True),
        pooled=False,
        engine_options={
            "pool_size": 5,
            "max_overflow": 0,
            "connect_args": {"timeout": 30, "server_settings": {"application_name": APP_NAME}},
        },
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _ok(raw: str = VALID_OUTPUT_JSON) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=100, output_units=20)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


def _assert_lock_free(observations: list[Observation], expected_calls: int) -> None:
    assert len(observations) == expected_calls
    for index, seen in enumerate(observations, start=1):
        assert seen.locked == (), f"call {index}: row locks held on {seen.locked}"
        assert seen.open_transactions == (), f"call {index}: {seen.open_transactions}"
        assert seen.row_counts["ai_requests"] == 1
        assert seen.row_counts["ai_budget_periods"] == 1
        assert seen.row_counts["ai_usage_records"] == index  # this call's row is committed
        assert seen.usage_statuses[-1] == "reserved"  # visible from another connection
        assert "reserved" not in seen.usage_statuses[:-1]  # earlier attempts are settled
        assert seen.request_status == "running"


async def _run(
    env: AiDbEnv,
    sessions: async_sessionmaker[AsyncSession],
    script: list[ScriptedResponse],
) -> tuple[SpyProvider, UUID]:
    workspace_id = await env.new_workspace()
    spy = SpyProvider(script)
    spy.observe = lambda: probe(env, workspace_id)
    orchestrator, _ = build_orchestrator(
        env, env.clock(), entries=ENTRIES, provider=spy, sessions=sessions
    )
    await orchestrator.run(_ctx(workspace_id), AiTaskRequest(task=TASK, instructions="synthetic"))
    return spy, workspace_id


async def test_the_first_provider_call_holds_no_transaction_and_no_row_lock(
    env: AiDbEnv, orchestrator_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """AC-38 (run), INV-6: the first call of ``run`` starts with no open transaction and no lock."""
    spy, _ = await _run(env, orchestrator_sessions, [_ok()])
    _assert_lock_free(spy.observations, 1)


async def test_a_repair_call_holds_no_transaction_and_no_row_lock(
    env: AiDbEnv, orchestrator_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """AC-38 (repair call), INV-6: the repair call is also made outside any transaction."""
    spy, _ = await _run(env, orchestrator_sessions, [_ok(BAD), _ok()])
    assert [m.role for m in spy.calls[1].request.messages][-2:] == ["assistant", "user"]  # repair
    _assert_lock_free(spy.observations, 2)


async def test_a_fallback_call_holds_no_transaction_and_no_row_lock(
    env: AiDbEnv, orchestrator_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """AC-38 (fallback call), INV-6: the call to the next candidate runs outside a transaction."""
    spy, _ = await _run(env, orchestrator_sessions, [ScriptedResponse.fail(Kind.TIMEOUT), _ok()])
    assert spy.calls[0].request.model != spy.calls[1].request.model  # a different candidate
    _assert_lock_free(spy.observations, 2)


async def test_the_probe_detects_a_held_row_lock_and_an_open_transaction(
    env: AiDbEnv, orchestrator_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Control: if the orchestrator's connection held a row lock inside a transaction, the probe
    would report it, so the clean results above are meaningful."""
    workspace_id = await env.new_workspace()
    await env.sync_request(workspace_id, env.clock())
    async with orchestrator_sessions() as session, session.begin():
        await session.execute(
            text("SELECT id FROM ai_requests WHERE workspace_id = :w FOR UPDATE"),
            {"w": workspace_id},
        )
        seen = await probe(env, workspace_id)
    assert "ai_requests" in seen.locked
    assert seen.open_transactions and all(started for _, started in seen.open_transactions)

