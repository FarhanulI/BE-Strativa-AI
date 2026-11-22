"""T-011 step 2: ``AiOrchestrator.run`` request row and refusal paths (database, local Postgres).

Covers spec 4.5 (sync lifecycle), the refusal endings of 10.3 (``no_route``, ``input_too_large``,
``provider_not_configured``, ``budget_exceeded``), D-33 (single refusal path before
``AiBudgetExceeded``), AC-16 (zero-call missing credentials, ``run`` part), AC-51 (no row, no usage
row, no reservation on a rejected call) and the ``run`` side of AC-62 (label stored). A refused
call leaves exactly one metadata-only request row, no usage row and no reservation, and the
provider is never called. Synthetic text only. Isolation and teardown rules are in
``tests/helpers/ai_request_db_env.py``; this fixture also registers the request rows the
orchestrator created, which the test cannot know in advance.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from app.ai_platform import (
    AiBudgetExceeded,
    AiCallContext,
    AiContextBlock,
    AiInputTooLarge,
    AiNoRoute,
    AiPlatformConfig,
    AiProviderNotConfigured,
    AiTaskName,
    AiTaskNotReady,
    AiTaskRegistry,
    AiTaskRequest,
    FakeAiProvider,
    OutputSchemaRegistry,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.orchestrator import ROUTING_VERSION, AiOrchestrator
from app.core import FakeClock, Settings, ValidationFailed
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.synthetic_catalog import catalog_dict, chat_entry, embed_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # interactive, low cost class
LABEL = "hooks.v3"
SYNTHETIC_KEY = "synthetic-test-key-not-real"  # a placeholder, never a real credential
# The estimate of the request below is a few hundred micro-USD; this limit is far below it.
TINY_BUDGET_USD = "0.0001"


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = ""


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


def _orchestrator(
    env: AiDbEnv,
    clock: FakeClock,
    *,
    entries: tuple[dict[str, Any], ...] | None = None,
    key: str | None = SYNTHETIC_KEY,
    budget_usd: str = "25",
    schemas_ready: bool = True,
) -> tuple[AiOrchestrator, FakeAiProvider]:
    values: dict[str, Any] = {"workspace_monthly_budget_usd": budget_usd}
    if key is not None:
        values["gemini_api_key"] = key
    config = AiPlatformConfig(_env_file=None, **values)
    # The configured chat provider id is the only one the config can give a key for.
    catalog = ModelCatalog.from_dict(catalog_dict(*(entries or (chat_entry(provider="gemini"),))))
    schemas = OutputSchemaRegistry()
    for task in AiTaskRegistry().list() if schemas_ready else ():
        if task.output_schema_name is not None:
            schemas.register(task.output_schema_name, 1, _Output)
    provider = FakeAiProvider()
    orchestrator = AiOrchestrator(
        env.sessions,
        config,
        catalog,
        clock,
        CircuitBreakerRegistry(clock, config),
        BudgetCoordinator(env.sessions, clock, config),
        provider,
        CharCountEstimator(),
        schemas=schemas,
    )
    return orchestrator, provider


def _request(task: AiTaskName = TASK, **overrides: Any) -> AiTaskRequest:
    return AiTaskRequest(
        task=task, instructions="synthetic instructions", instructions_version=LABEL, **overrides
    )


async def _rows(env: AiDbEnv, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        result = await session.execute(
            text("SELECT * FROM ai_requests WHERE workspace_id = :w ORDER BY created_at"),
            {"w": workspace_id},
        )
        return list(result.all())


async def _count(env: AiDbEnv, sql: str, workspace_id: UUID) -> int:
    async with env.sessions() as session, session.begin():
        return int((await session.execute(text(sql), {"w": workspace_id})).scalar_one())


async def _usage_rows(env: AiDbEnv, workspace_id: UUID) -> int:
    return await _count(
        env, "SELECT count(*) FROM ai_usage_records WHERE workspace_id = :w", workspace_id
    )


async def _reserved(env: AiDbEnv, workspace_id: UUID) -> int:
    return await _count(
        env,
        "SELECT COALESCE(SUM(reserved_micro_usd), 0) FROM ai_budget_periods "
        "WHERE workspace_id = :w",
        workspace_id,
    )


async def _assert_refused_cleanly(
    env: AiDbEnv,
    provider: FakeAiProvider,
    workspace_id: UUID,
    error_code: str,
) -> Any:
    rows = await _rows(env, workspace_id)
    assert len(rows) == 1, "exactly one metadata-only request row"
    row = rows[0]
    assert row.mode == "sync" and row.scope == "workspace" and row.task == TASK.value
    assert row.status == "failed" and row.error_code == error_code
    assert row.completed_at is not None and row.started_at is not None
    assert row.routing_version == ROUTING_VERSION
    assert row.instructions_version == LABEL  # AC-62, run side (D-36)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (0, 0, 0)
    assert row.idempotency_key is None and row.request_fingerprint is None
    assert row.input_payload is None and row.output_payload is None
    assert row.lease_epoch == 0
    assert await _usage_rows(env, workspace_id) == 0, "no usage row"
    assert await _reserved(env, workspace_id) == 0, "no reservation"
    assert provider.calls == (), "no provider call"
    return row


async def test_no_route_ends_the_row_failed_with_no_usage_and_no_reservation(
    env: AiDbEnv,
) -> None:
    """Spec 4.5 / 10.3: no model has the capability, so ``AiNoRoute`` and ``no_route``."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(
        env, env.clock(), entries=(embed_entry(provider="gemini"),)
    )
    with pytest.raises(AiNoRoute):
        await orchestrator.run(
            AiCallContext.for_worker(workspace_id=workspace_id, request_id="r"), _request()
        )
    await _assert_refused_cleanly(env, provider, workspace_id, "no_route")


async def test_input_too_large_ends_the_row_failed(env: AiDbEnv) -> None:
    """Spec 10.2 step 3: the padded input does not fit any model's context window."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(env, env.clock())
    huge = AiContextBlock(text="x" * 600_000)  # ~150,000 units against a 100,000 window
    with pytest.raises(AiInputTooLarge):
        await orchestrator.run(
            AiCallContext.for_worker(workspace_id=workspace_id, request_id="r"),
            _request(context=[huge]),
        )
    await _assert_refused_cleanly(env, provider, workspace_id, "input_too_large")


async def test_missing_credentials_make_zero_calls_and_end_provider_not_configured(
    env: AiDbEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-16 (``run`` part): no reservation, no provider call, no usage row, row failed."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(env, env.clock(), key=None)
    with pytest.raises(AiProviderNotConfigured):
        await orchestrator.run(
            AiCallContext.for_worker(workspace_id=workspace_id, request_id="r"), _request()
        )
    await _assert_refused_cleanly(env, provider, workspace_id, "provider_not_configured")


async def test_budget_refusal_goes_through_the_single_refusal_path_before_the_error(
    env: AiDbEnv,
) -> None:
    """D-33: the flag, one ``ai.budget_exhausted`` event and one audit record exist when
    ``AiBudgetExceeded`` surfaces; a second refusal publishes nothing more."""
    clock = env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(env, clock, budget_usd=TINY_BUDGET_USD)
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(ctx, _request())
    await _assert_refused_cleanly(env, provider, workspace_id, "budget_exceeded")

    row_id = await env.find_budget_row(workspace_id, clock)
    assert row_id is not None
    budget = await env.budget_row(row_id)
    assert budget.exhausted_notified_at is not None
    assert budget.reserved_micro_usd == 0 and budget.spent_micro_usd == 0
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1

    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(ctx, _request())
    assert len(await _rows(env, workspace_id)) == 2  # one metadata-only row per refused call
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1
    assert await _usage_rows(env, workspace_id) == 0 and provider.calls == ()


async def test_a_rejected_call_leaves_no_row_at_all(env: AiDbEnv) -> None:
    """AC-51, AC-26, spec 4.5: pre-routing rejections write nothing."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(env, env.clock())
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")

    unready, _ = _orchestrator(env, env.clock(), schemas_ready=False)
    with pytest.raises(AiTaskNotReady):
        await unready.run(ctx, _request())
    with pytest.raises(AiTaskNotReady):
        await orchestrator.run(ctx, _request(output_schema_version=9))
    with pytest.raises(ValidationFailed):
        await orchestrator.run(AiCallContext.system(request_id="s"), _request())

    assert await _rows(env, workspace_id) == []
    assert await _usage_rows(env, workspace_id) == 0 and await _reserved(env, workspace_id) == 0
    assert provider.calls == ()


async def test_a_routable_call_creates_a_running_row_before_anything_else(env: AiDbEnv) -> None:
    """Spec 4.5 creation: ``mode='sync'``, ``running``, ``started_at = now``, lease and
    idempotency columns NULL. Transitional: the provider call arrives in step 3, so the call
    still stops at ``NotImplementedError`` and the row is left ``running`` (step 3 replaces it).
    """
    clock = env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = _orchestrator(env, clock)
    with pytest.raises(NotImplementedError):
        await orchestrator.run(
            AiCallContext.for_worker(workspace_id=workspace_id, request_id="req-9"), _request()
        )
    (row,) = await _rows(env, workspace_id)
    assert (row.mode, row.status, row.actor_type) == ("sync", "running", "worker")
    assert row.started_at == clock.now() and row.completed_at is None and row.error_code is None
    assert row.correlation_request_id == "req-9" and row.instructions_version == LABEL
    assert row.output_schema_name == "HookVariationSet" and row.output_schema_version == 1
    assert row.lease_epoch == 0 and row.idempotency_key is None and row.input_payload is None
    assert await _usage_rows(env, workspace_id) == 0 and provider.calls == ()
