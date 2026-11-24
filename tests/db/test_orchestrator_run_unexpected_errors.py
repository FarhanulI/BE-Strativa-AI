"""T-023 step 2: ``AiOrchestrator.run`` after an unexpected exception (local Postgres).

Covers INV-7 (every attempt ends settled or abandoned), INV-14 (an abandoned reservation is charged
at its estimate) and spec 4.5 (a sync row ends ``succeeded`` or ``failed``; AC-45, ``run`` part).
Owner decisions (T-023): D-A the row ends ``failed`` with ``execution_abandoned``; D-B the in-flight
usage row becomes ``abandoned`` at its reserved estimate and the reservation is released; D-C the
original exception reaches the caller unchanged; D-D a cancelled call is cleaned up the same way
(shielded) and stays cancelled.

These tests are written RED: against the T-011 code, which catches only ``AiBudgetExceeded``, the
row stays ``running`` and the usage row stays ``reserved``. Synthetic text only.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.ai_platform import AiCallContext, AiTaskName, AiTaskRequest, ScriptedResponse
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.fake_provider import FakeAiProvider
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import VALID_OUTPUT_JSON, build_orchestrator

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
SENTINEL = "zz-sentinel-boom-7731"


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


async def _assert_abandoned_cleanly(
    env: AiDbEnv, workspace_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    """D-A, D-B: the row failed with ``execution_abandoned`` and the one usage row is abandoned at
    its estimate; the budget holds no reservation and carries the estimate as spent."""
    (row,) = await _rows(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", workspace_id)
    assert row.status == "failed", f"request row left {row.status!r}"
    assert row.error_code == "execution_abandoned"
    assert row.completed_at is not None
    (usage,) = await _rows(
        env, "SELECT * FROM ai_usage_records WHERE workspace_id = :w", workspace_id
    )
    assert usage.status == "abandoned", f"usage row left {usage.status!r}"
    assert usage.reserved_micro_usd > 0
    assert usage.cost_micro_usd == usage.reserved_micro_usd  # INV-14: charged at the estimate
    assert usage.finished_at is not None
    (budget,) = await _rows(
        env,
        "SELECT reserved_micro_usd, spent_micro_usd FROM ai_budget_periods "
        "WHERE workspace_id = :w",
        workspace_id,
    )
    assert budget.reserved_micro_usd == 0
    assert budget.spent_micro_usd == usage.reserved_micro_usd
    stored = json.dumps([[str(v) for v in record] for record in (row, usage)], default=str)
    assert SENTINEL not in stored and SENTINEL not in caplog.text  # no content in rows or logs


def _boom(_request: Any) -> ScriptedResponse:
    raise RuntimeError(SENTINEL)


async def test_an_unexpected_provider_exception_fails_the_row_and_abandons_the_reservation(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """INV-7, INV-14, AC-45 (run), D-A to D-C: a non-``ProviderCallError`` from the provider."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), provider=FakeAiProvider(responder=_boom)
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == SENTINEL  # D-C: the original exception, unwrapped
    assert len(provider.calls) == 1
    await _assert_abandoned_cleanly(env, workspace_id, caplog)


class _SettleFails(BudgetCoordinator):
    """Settlement raises, as a database error while settling would (the call itself succeeded)."""

    async def settle_call(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(SENTINEL)


async def test_a_failure_while_settling_fails_the_row_and_abandons_the_reservation(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """INV-7, INV-14, AC-45 (run), D-A to D-C: the provider answered but settling raised, so the
    usage row is still ``reserved`` and must be abandoned at its estimate."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        script=[ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=100, output_units=20)],
        coordinator_factory=_SettleFails,
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == SENTINEL
    assert len(provider.calls) == 1
    await _assert_abandoned_cleanly(env, workspace_id, caplog)


async def test_a_cancelled_call_is_cleaned_up_and_stays_cancelled(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """INV-7, INV-14, AC-45 (run), D-D: cancelling ``run`` during the provider call still ends the
    row and abandons the reservation (shielded cleanup), and the cancellation is not swallowed."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        script=[ScriptedResponse.ok(VALID_OUTPUT_JSON, delay_seconds=3600.0)],
    )
    with caplog.at_level(logging.DEBUG):
        task = asyncio.ensure_future(orchestrator.run(_ctx(workspace_id), _request()))
        for _ in range(500):  # wait until the provider call has started (it is recorded first)
            if provider.calls:
                break
            await asyncio.sleep(0.01)
        assert len(provider.calls) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    await _assert_abandoned_cleanly(env, workspace_id, caplog)
