"""T-024 step 3: the owner's edge decisions D-A to D-D for the cleanup of ``AiOrchestrator.run``
(local Postgres).

* D-C (b): ``ai_requests.routing_version`` stays NULL when the fault came before routing made a
  decision, and carries the version when routing had run. Spec 4.1 (nullable column). INV-7, AC-45.
* D-A (a): a cancellation that arrives while the cleanup runs is held until the cleanup is done and
  is then dropped; the caller sees the original exception. INV-7, INV-14.
* D-D (a): an error raised by the cleanup is dropped silently, with no log record. INV-18.
D-B (a), no bound on the cleanup, is an accepted risk recorded in the traceability Notes, not a
test. Synthetic text only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from structlog.testing import capture_logs

from app.ai_platform import AiCallContext, AiTaskName, AiTaskRequest, ScriptedResponse
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.fake_provider import FakeAiProvider
from app.ai_platform.orchestrator import ROUTING_VERSION
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import build_orchestrator

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
ORIGINAL = "zz-sentinel-original-9941"  # the exception the caller must see
CLEANUP = "zz-sentinel-cleanup-9942"  # the exception raised by a failing cleanup


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


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


def _request() -> AiTaskRequest:
    return AiTaskRequest(task=TASK, instructions="synthetic")


async def _rows(env: AiDbEnv, sql: str, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        return list((await session.execute(text(sql), {"w": workspace_id})).all())


async def _request_row(env: AiDbEnv, workspace_id: UUID) -> Any:
    (row,) = await _rows(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", workspace_id)
    return row


def _raising(message: str) -> Any:
    def responder(_request: Any) -> ScriptedResponse:
        raise RuntimeError(message)

    return responder


# --- D-C (b): routing_version before routing -----------------------------------------------------


class _BreakerFails(CircuitBreakerRegistry):
    """Reading the breaker state raises. ``run`` reads it while building the routing input, so the
    fault comes before routing has made any decision."""

    def unavailable_models(self) -> Any:
        raise RuntimeError(ORIGINAL)


async def test_a_fault_before_routing_leaves_routing_version_null(env: AiDbEnv) -> None:
    """D-C (b), INV-7, AC-45 (run), spec 4.1: no routing decision was made, so the row ends
    ``failed`` with ``execution_abandoned`` and ``routing_version`` stays NULL (not a claim that a
    decision was made). No provider call, no usage row."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(env, env.clock(), breaker_factory=_BreakerFails)
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL
    assert not provider.calls
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"
    assert row.completed_at is not None
    assert row.routing_version is None
    assert not await _rows(
        env, "SELECT 1 FROM ai_usage_records WHERE workspace_id = :w", workspace_id
    )


async def test_a_fault_after_routing_records_the_routing_version(env: AiDbEnv) -> None:
    """D-C (b): once routing has decided, an unexpected fault in an attempt still records the
    version of the rules that decided."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), provider=FakeAiProvider(responder=_raising(ORIGINAL))
    )
    with pytest.raises(RuntimeError):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"
    assert row.routing_version == ROUTING_VERSION


# --- D-A (a): a cancellation during cleanup is held, then dropped ---------------------------------


class _SlowAbandon(BudgetCoordinator):
    """Abandoning takes a moment and signals when it has started, so a test can cancel the caller
    while the cleanup is running."""

    started: asyncio.Event

    async def abandon_call(self, *args: Any, **kwargs: Any) -> Any:
        type(self).started.set()
        await asyncio.sleep(0.2)
        return await super().abandon_call(*args, **kwargs)


async def test_a_cancellation_during_cleanup_is_held_and_the_original_is_raised(
    env: AiDbEnv,
) -> None:
    """D-A (a), INV-7, INV-14: the provider raises, and the caller is cancelled while the abandon
    runs. The cleanup still finishes (the usage row is ``abandoned`` at its estimate, the request
    row ``failed``), and the caller sees the provider's exception, not ``CancelledError``. This
    pins today's behavior; D-A (b) would re-deliver the cancellation instead."""
    workspace_id = await env.new_workspace()
    _SlowAbandon.started = asyncio.Event()
    orchestrator, _ = build_orchestrator(
        env,
        env.clock(),
        provider=FakeAiProvider(responder=_raising(ORIGINAL)),
        coordinator_factory=_SlowAbandon,
    )
    task = asyncio.ensure_future(orchestrator.run(_ctx(workspace_id), _request()))
    await asyncio.wait_for(_SlowAbandon.started.wait(), timeout=30)
    task.cancel()
    with pytest.raises(RuntimeError) as raised:
        await task
    assert str(raised.value) == ORIGINAL
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"
    (usage,) = await _rows(
        env, "SELECT * FROM ai_usage_records WHERE workspace_id = :w", workspace_id
    )
    assert usage.status == "abandoned" and usage.cost_micro_usd == usage.reserved_micro_usd > 0
    (budget,) = await _rows(
        env,
        "SELECT reserved_micro_usd, spent_micro_usd FROM ai_budget_periods WHERE workspace_id = :w",
        workspace_id,
    )
    assert budget.reserved_micro_usd == 0 and budget.spent_micro_usd == usage.reserved_micro_usd


# --- D-D (a): a dropped cleanup error is silent ---------------------------------------------------


class _AbandonFails(BudgetCoordinator):
    async def abandon_call(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(CLEANUP)


async def test_a_dropped_cleanup_error_writes_no_log_record(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """D-D (a), INV-18: the cleanup error is dropped without a log record in structlog or the
    standard log, so neither its message nor its class name appears. Pins today's behavior; D-D (b)
    would write one fixed-message record with the exception class name only."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env,
        env.clock(),
        provider=FakeAiProvider(responder=_raising(ORIGINAL)),
        coordinator_factory=_AbandonFails,
    )
    with capture_logs() as records, caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as raised:
            await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL
    assert CLEANUP not in caplog.text and CLEANUP not in repr(records)
    assert not [r for r in records if r.get("log_level") in {"error", "warning", "critical"}]
