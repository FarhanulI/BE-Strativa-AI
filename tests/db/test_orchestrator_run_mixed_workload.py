"""T-025 step 2: AC-36 / INV-13 driven through ``AiOrchestrator.run`` (local Postgres).

After a mixed workload (successes, a repair, a fallback, invalid outputs, a failed call, a budget
refusal) every budget row with ``reserved = 0`` equals the sum of its usage records. The existing
``test_mixed_workload_reconciles`` drives the repository directly; this one goes through the
orchestrator. Synthetic text only; the provider is the scripted fake.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.ai_platform import (
    AiBudgetExceeded,
    AiCallContext,
    AiOutputInvalid,
    AiProviderUnavailable,
    AiTaskName,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform import budget_repository as repo
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
IN_UNITS, OUT_UNITS = 1000, 200
BAD_OUTPUT = json.dumps({"value": 5})
TINY_BUDGET_USD = "0.0001"
ENTRIES = tuple(
    chat_entry(provider=CHAT_PROVIDER, model=f"synthetic-{name}", latency_p50_ms=500 + 100 * index)
    for index, name in enumerate("abcd")
)


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


def _ok(raw: str = VALID_OUTPUT_JSON) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=IN_UNITS, output_units=OUT_UNITS)


def _fail(kind: Kind) -> ScriptedResponse:
    return ScriptedResponse.fail(kind, input_units=IN_UNITS, output_units=0)


async def _rows(env: AiDbEnv, sql: str, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        return list((await session.execute(text(sql), {"w": workspace_id})).all())


async def test_a_mixed_run_workload_reconciles_with_the_usage_ledger(env: AiDbEnv) -> None:
    """AC-36, INV-13: successes, repair, fallback, invalid outputs, a failed call and a budget
    refusal leave ``reserved = 0`` and ``spent`` equal to the sum of the usage records."""
    clock = env.clock()
    workspace_id = await env.new_workspace()
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    request = AiTaskRequest(task=TASK, instructions="synthetic instructions")
    script = [
        _ok(),  # run 1: succeeds on model a
        _ok(BAD_OUTPUT), _ok(),  # run 2: invalid, one repair call to a, then valid
        _fail(Kind.TIMEOUT), _ok(),  # run 3: a times out, falls back to b
        *[_ok(BAD_OUTPUT)] * 6,  # run 4: every call invalid, three models with a repair each
        _fail(Kind.BAD_REQUEST),  # run 5: one failed attempt, no fallback
    ]  # fmt: skip
    orchestrator, provider = build_orchestrator(env, clock, entries=ENTRIES, script=script)
    refuser, _ = build_orchestrator(
        env, clock, entries=ENTRIES, budget_usd=TINY_BUDGET_USD
    )  # same database, a limit far below any estimate

    await orchestrator.run(ctx, request)
    clock.advance(timedelta(seconds=61))  # keep the breaker window out of the picture
    await orchestrator.run(ctx, request)
    clock.advance(timedelta(seconds=61))
    await orchestrator.run(ctx, request)
    clock.advance(timedelta(seconds=61))
    with pytest.raises(AiOutputInvalid):
        await orchestrator.run(ctx, request)
    clock.advance(timedelta(seconds=61))
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(ctx, request)
    with pytest.raises(AiBudgetExceeded):
        await refuser.run(ctx, request)
    assert len(provider.calls) == 1 + 2 + 2 + 6 + 1  # the refusal made no provider call

    usage = await _rows(
        env,
        "SELECT * FROM ai_usage_records WHERE workspace_id = :w ORDER BY created_at",
        workspace_id,
    )
    assert {u.status for u in usage} == {"succeeded", "failed"}
    assert {u.call_kind for u in usage} == {"generation", "repair"}
    requests = await _rows(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", workspace_id)
    assert sorted(r.status for r in requests) == ["failed"] * 3 + ["succeeded"] * 3
    assert "budget_exceeded" in {r.error_code for r in requests}

    row_id = await env.find_budget_row(workspace_id, clock)
    assert row_id is not None
    async with env.sessions() as session, session.begin():
        assert await repo.reconciliation_query(session, [row_id]) == []
    budget = await env.budget_row(row_id)
    assert budget.reserved_micro_usd == 0
    assert budget.spent_micro_usd == sum(u.cost_micro_usd for u in usage) > 0
    assert budget.spent_micro_usd == sum(r.cost_micro_usd for r in requests)
