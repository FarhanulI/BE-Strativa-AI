"""T-011 step 3: ``AiOrchestrator.run`` single successful call (database, local Postgres).

Covers AC-59 (the reservation equals the Router estimate), D-31 (the provider gets exactly the
effective output cap), D-22 (the configured key is passed explicitly), AC-22 (strict validation
before anything is returned), AC-29 (``run`` part: ``free_tier`` metering at catalog price and the
``ai_requests`` totals), INV-7 (the reservation is released once at settlement), INV-8 (invalid
output is never returned or stored), spec 4.5 (row lifecycle, ``persist_result``) and the ``run``
side of AC-62. A first call that does not succeed is settled ``failed`` and stops at
``NotImplementedError`` (fallback and repair are steps 4 to 6). Synthetic text only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.ai_platform import (
    AiBudgetExceeded,
    AiCallContext,
    AiTaskName,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.failure_policy import ProviderFailureKind
from app.ai_platform.messages import build_generation_messages
from app.ai_platform.orchestrator import ROUTING_VERSION
from app.ai_platform.pricing import cost_micro_usd
from app.ai_platform.provider import ProviderGenerationRequest
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.orchestrator_db import (
    SYNTHETIC_KEY,
    VALID_OUTPUT_JSON,
    OutputForTests,
    build_orchestrator,
)
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # interactive, default output cap 1500
LABEL = "hooks.v3"
INSTRUCTIONS = "synthetic instructions"
IN_UNITS, OUT_UNITS = 1000, 200
# Catalog prices of the synthetic chat entry: 150,000 / 600,000 micro-USD per million units.
EXPECTED_COST = cost_micro_usd(IN_UNITS, 150_000) + cost_micro_usd(OUT_UNITS, 600_000)


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


def _request(**overrides: Any) -> AiTaskRequest:
    return AiTaskRequest(
        task=TASK, instructions=INSTRUCTIONS, instructions_version=LABEL, **overrides
    )


def _ok(raw: str = VALID_OUTPUT_JSON) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=IN_UNITS, output_units=OUT_UNITS)


async def _one(env: AiDbEnv, sql: str, **params: Any) -> Any:
    async with env.sessions() as session, session.begin():
        return (await session.execute(text(sql), params)).one()


async def _request_row(env: AiDbEnv, workspace_id: UUID) -> Any:
    return await _one(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", w=workspace_id)


async def _usage_rows(env: AiDbEnv, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        result = await session.execute(
            text("SELECT * FROM ai_usage_records WHERE workspace_id = :w ORDER BY attempt_no"),
            {"w": workspace_id},
        )
        return list(result.all())


async def _budget(env: AiDbEnv, workspace_id: UUID) -> Any:
    return await _one(
        env,
        "SELECT reserved_micro_usd, spent_micro_usd FROM ai_budget_periods WHERE workspace_id = :w",
        w=workspace_id,
    )


def _expected_estimate() -> int:
    """The Router estimate, computed independently: margin-padded input plus the output cap."""
    messages, _ = build_generation_messages(INSTRUCTIONS, [])
    units = CharCountEstimator().estimate_messages(messages)
    padded = -(-(units * 110) // 100)  # default context_safety_margin_percent is 10
    return cost_micro_usd(padded, 150_000) + cost_micro_usd(1500, 600_000)


async def test_successful_call_returns_a_validated_result_and_settles_one_usage_row(
    env: AiDbEnv,
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(env, clock, script=[_ok()])
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="req-9")

    result = await orchestrator.run(ctx, _request())

    # The result (spec 5.2): a validated instance, usage totals, opaque routing id, no model name.
    assert isinstance(result.output, OutputForTests) and result.output.value == "ok"
    assert (result.task, result.output_schema_name, result.output_schema_version) == (
        TASK,
        "HookVariationSet",
        1,
    )
    assert result.usage.model_dump() == {
        "input_units": IN_UNITS,
        "output_units": OUT_UNITS,
        "cost_micro_usd": EXPECTED_COST,
        "call_count": 1,
    }
    dumped = result.model_dump_json()
    assert "gemini" not in dumped and "fake-chat" not in dumped

    # The request row (spec 4.5): created running, ended succeeded, totals are the usage sums.
    row = await _request_row(env, workspace_id)
    assert row.id == result.request_id
    assert (row.mode, row.status, row.actor_type, row.scope) == (
        "sync",
        "succeeded",
        "worker",
        "workspace",
    )
    assert row.error_code is None and row.completed_at is not None
    assert row.started_at == clock.now() and row.correlation_request_id == "req-9"
    assert row.instructions_version == LABEL  # AC-62, run side
    assert row.routing_version == ROUTING_VERSION
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (
        IN_UNITS,
        OUT_UNITS,
        EXPECTED_COST,
    )
    assert row.output_payload is None  # persist_result defaults to False
    assert row.lease_epoch == 0 and row.idempotency_key is None and row.input_payload is None

    # Exactly one usage row, settled, reservation equal to the Router estimate (AC-59, D-24).
    (usage,) = await _usage_rows(env, workspace_id)
    assert usage.id == result.routing_id and usage.request_id == result.request_id
    assert (usage.attempt_no, usage.call_kind, usage.route_rank) == (1, "generation", 1)
    assert usage.status == "succeeded" and usage.error_code is None
    assert usage.reserved_micro_usd == _expected_estimate()
    assert (usage.input_units, usage.output_units, usage.cost_micro_usd) == (
        IN_UNITS,
        OUT_UNITS,
        EXPECTED_COST,
    )
    assert usage.billing_mode == "free_tier"  # AC-29: metered at catalog price in both modes
    assert usage.routing_version == ROUTING_VERSION and usage.schema_valid is True
    assert usage.finish_reason == "stop" and usage.finished_at is not None
    # CP-3 (spec 4.2 rev 10, 10.5): the stored snapshot is the Router's, provider included.
    (entry,) = usage.candidate_snapshot
    assert set(entry) == {"provider", "model", "eligible", "reason_code"}
    assert entry["provider"] == "gemini" and entry["eligible"] is True
    assert entry["model"] == usage.model and entry["reason_code"] is None

    # Settlement released the reservation exactly once and added the actual cost (INV-7).
    budget = await _budget(env, workspace_id)
    assert (budget.reserved_micro_usd, budget.spent_micro_usd) == (0, EXPECTED_COST)

    # What the provider received: the configured key (D-22), the effective cap (D-31), no tools.
    (call,) = provider.calls
    assert call.api_key is not None and call.api_key.get_secret_value() == SYNTHETIC_KEY
    assert call.request.max_output_units == 1500
    assert call.request.provider == "gemini" and call.request.response_mode == "json_schema"
    assert call.request.messages[0].role == "system"
    assert INSTRUCTIONS in call.request.messages[0].content
    assert all(m.role != "assistant" for m in call.request.messages)
    forbidden = {"tools", "functions", "tool_choice"}
    assert not forbidden & set(ProviderGenerationRequest.model_fields)


async def test_the_effective_output_cap_is_clamped_to_the_model_maximum(env: AiDbEnv) -> None:
    """D-31: the provider receives exactly the clamped value, not the task default."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=(chat_entry(provider="gemini", max_output_units=700),),
        script=[_ok()],
    )
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    await orchestrator.run(ctx, _request())
    assert provider.calls[0].request.max_output_units == 700
    (usage,) = await _usage_rows(env, workspace_id)
    assert usage.reserved_micro_usd == (
        _expected_estimate() - cost_micro_usd(1500, 600_000) + cost_micro_usd(700, 600_000)
    )


async def test_persist_result_stores_the_output_only_when_asked(env: AiDbEnv) -> None:
    """Spec 4.5: ``output_payload`` is stored only with ``persist_result=True``."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(env, env.clock(), script=[_ok(), _ok()])
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    await orchestrator.run(ctx, _request(persist_result=True))
    await orchestrator.run(ctx, _request())
    async with env.sessions() as session, session.begin():
        rows = (
            await session.execute(
                text(
                    "SELECT output_payload FROM ai_requests WHERE workspace_id = :w "
                    "ORDER BY created_at"
                ),
                {"w": workspace_id},
            )
        ).all()
    assert [r.output_payload for r in rows] == [json.loads(VALID_OUTPUT_JSON), None]


async def test_missing_provider_usage_falls_back_to_the_estimator(env: AiDbEnv) -> None:
    """Spec 12.1: a response without usage is metered from the platform's own estimate."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env, env.clock(), script=[ScriptedResponse.ok(VALID_OUTPUT_JSON)]
    )
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    result = await orchestrator.run(ctx, _request())
    messages, _ = build_generation_messages(INSTRUCTIONS, [])
    estimator = CharCountEstimator()
    assert result.usage.input_units == estimator.estimate_messages(messages)
    assert result.usage.output_units == estimator.estimate_text(VALID_OUTPUT_JSON)


async def test_invalid_output_is_never_returned_or_stored_and_the_attempt_is_settled_failed(
    env: AiDbEnv,
) -> None:
    """INV-8, AC-22: strict validation fails -> no result, no payload; the usage row is settled
    ``failed`` with counts and type names only, and the reservation is released (INV-7).
    Repair and fallback are steps 4 to 6, so the call stops at ``NotImplementedError``."""
    workspace_id = await env.new_workspace()
    bad = json.dumps({"value": 5, "extra": "zz-sentinel-output-3391"})
    orchestrator, _ = build_orchestrator(env, env.clock(), script=[_ok(bad)])
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    with pytest.raises(NotImplementedError):
        await orchestrator.run(ctx, _request(persist_result=True))
    (usage,) = await _usage_rows(env, workspace_id)
    assert usage.status == "failed" and usage.error_code == "output_invalid"
    assert usage.schema_valid is False and usage.validation_error_count == 2
    assert sorted(usage.validation_error_types) == ["extra_forbidden", "string_type"]
    assert (usage.input_units, usage.output_units, usage.cost_micro_usd) == (
        IN_UNITS,
        OUT_UNITS,
        EXPECTED_COST,
    )
    assert "zz-sentinel-output-3391" not in json.dumps([str(v) for v in usage], default=str)
    row = await _request_row(env, workspace_id)
    assert row.output_payload is None and row.status == "running"
    budget = await _budget(env, workspace_id)
    assert (budget.reserved_micro_usd, budget.spent_micro_usd) == (0, EXPECTED_COST)


@pytest.mark.parametrize(
    ("scripted", "code", "cost"),
    [
        (ScriptedResponse.fail(ProviderFailureKind.TIMEOUT), "provider_timeout", 0),
        (
            ScriptedResponse.fail(
                ProviderFailureKind.HTTP_5XX, input_units=IN_UNITS, output_units=0
            ),
            "provider_unavailable",
            cost_micro_usd(IN_UNITS, 150_000),
        ),
    ],
)
async def test_a_failed_first_call_is_settled_with_reported_usage_only(
    env: AiDbEnv, scripted: ScriptedResponse, code: str, cost: int
) -> None:
    """Spec 12.1: a provider error costs reported units x price, or 0 when none were reported."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(env, env.clock(), script=[scripted])
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    with pytest.raises(NotImplementedError):
        await orchestrator.run(ctx, _request())
    (usage,) = await _usage_rows(env, workspace_id)
    assert usage.status == "failed" and usage.error_code == code
    assert usage.cost_micro_usd == cost and usage.schema_valid is None
    budget = await _budget(env, workspace_id)
    assert (budget.reserved_micro_usd, budget.spent_micro_usd) == (0, cost)


class _RefusingCoordinator(BudgetCoordinator):
    """Simulates the live budget moving between the snapshot and the reservation (spec 12.3)."""

    async def reserve_for_call(self, scope: Any, workspace_id: Any, *args: Any) -> Any:
        await self.refuse_for_call(scope, workspace_id, "GENERATE_HOOK_VARIATIONS")
        raise AiBudgetExceeded()


async def test_a_reservation_refusal_ends_the_row_failed_budget_exceeded(env: AiDbEnv) -> None:
    """Spec 12.3 step 4 / 4.5: refusal at reservation time -> row ``failed``, no usage row."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), script=[_ok()], coordinator_factory=_RefusingCoordinator
    )
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(ctx, _request())
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "budget_exceeded"
    assert row.completed_at is not None
    assert await _usage_rows(env, workspace_id) == [] and provider.calls == ()


async def test_the_deadline_remaining_is_the_provider_timeout(env: AiDbEnv) -> None:
    """The call timeout is the time left of the latency-class deadline (20 s, interactive)."""
    clock = env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(env, clock, script=[_ok()])
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")
    await orchestrator.run(ctx, _request())
    assert provider.calls[0].request.timeout_seconds == pytest.approx(20.0)
