"""T-023 step 4: clauses of AC-29, AC-59 and AC-16 that the T-011 audit found unasserted (local
Postgres). Tests only; the orchestrator is not changed in this step.

* AC-29: the recorded cost equals an independently computed ``ceil`` formula (not the production
  ``cost_micro_usd``), the row carries ``price_version`` and ``period_start``, the request totals
  equal the sum of its rows, and a ``free_tier`` call records the same nonzero metered cost as the
  same call configured ``paid`` (the figure is the application's metered cost, not an invoice,
  which would be 0 for a free-tier call).
* AC-59, second sentence: with identical figures the Router's step 7 and the atomic reservation
  agree. A candidate the Router passes is admitted (the boundary is inclusive); one it removes is
  refused by a reservation of that same amount against the same budget.
* AC-16: when every candidate fails with a connection error, a rate limit, an auth failure, a
  truncation or a timeout, the request row carries the code of the last failure and the raised
  class is ``AiProviderUnavailable``, with one attempt per model and the cap of three models.
Synthetic text only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.ai_platform import (
    AiBudgetExceeded,
    AiCallContext,
    AiProviderUnavailable,
    AiTaskName,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.messages import build_generation_messages
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # default output cap 1500
INSTRUCTIONS = "synthetic instructions"
IN_PRICE, OUT_PRICE = 150_000, 600_000  # micro-USD per million units, the synthetic chat entry
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


def _ceil_cost(units: int, price_per_million: int) -> int:
    """The spec's metered cost, written out here: ``ceil(units * price / 1,000,000)``."""
    return -(-(units * price_per_million) // 1_000_000)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


def _request() -> AiTaskRequest:
    return AiTaskRequest(task=TASK, instructions=INSTRUCTIONS)


async def _rows(env: AiDbEnv, sql: str, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        return list((await session.execute(text(sql), {"w": workspace_id})).all())


async def _usage(env: AiDbEnv, workspace_id: UUID) -> list[Any]:
    return await _rows(
        env,
        "SELECT * FROM ai_usage_records WHERE workspace_id = :w ORDER BY attempt_no",
        workspace_id,
    )


async def _request_row(env: AiDbEnv, workspace_id: UUID) -> Any:
    (row,) = await _rows(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", workspace_id)
    return row


# --- AC-29 ---------------------------------------------------------------------------------------

# Units chosen so neither part divides evenly: the round-up is exercised.
IN_UNITS, OUT_UNITS = 1234, 321
EXPECTED_COST = _ceil_cost(IN_UNITS, IN_PRICE) + _ceil_cost(OUT_UNITS, OUT_PRICE)  # 186 + 193


def _metered_ok() -> ScriptedResponse:
    return ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=IN_UNITS, output_units=OUT_UNITS)


async def test_the_recorded_cost_is_the_independent_ceil_with_price_version_and_period(
    env: AiDbEnv,
) -> None:
    """AC-29: units, integer micro-USD cost equal to the independent ``ceil`` formula,
    ``price_version``, ``billing_mode``, route fields and ``period_start``; the request totals
    equal the sum of its rows."""
    assert EXPECTED_COST == 379  # 185.1 rounds up to 186 and 192.6 to 193, by hand
    clock = env.clock(month=6, day=15)
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(env, clock, entries=ENTRIES[:1], script=[_metered_ok()])
    await orchestrator.run(_ctx(workspace_id), _request())

    (usage,) = await _usage(env, workspace_id)
    assert (usage.input_units, usage.output_units) == (IN_UNITS, OUT_UNITS)
    assert usage.cost_micro_usd == EXPECTED_COST
    assert usage.price_version == "test-prices-1" and usage.catalog_version == "test-1"
    assert usage.billing_mode == "free_tier"
    assert (usage.attempt_no, usage.route_rank, usage.call_kind) == (1, 1, "generation")
    assert usage.period_start == clock.now().date().replace(day=1)
    row = await _request_row(env, workspace_id)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (
        usage.input_units,
        usage.output_units,
        usage.cost_micro_usd,
    )


async def test_a_free_tier_call_records_the_same_metered_cost_as_the_same_call_paid(
    env: AiDbEnv,
) -> None:
    """AC-29: the cost is the metered cost at the catalog list price for both billing modes. The
    free-tier figure is nonzero and equals the paid one, so it is the application's accounting
    figure and not an invoice (an invoice for a free-tier call may be 0)."""
    costs: dict[str, int] = {}
    for mode in ("free_tier", "paid"):
        workspace_id = await env.new_workspace()
        orchestrator, _ = build_orchestrator(
            env,
            env.clock(),
            entries=ENTRIES[:1],
            config_values={"gemini_billing_mode": mode},
            script=[_metered_ok()],
        )
        await orchestrator.run(_ctx(workspace_id), _request())
        (usage,) = await _usage(env, workspace_id)
        assert usage.billing_mode == mode
        costs[mode] = usage.cost_micro_usd
    assert costs["free_tier"] > 0, "a free-tier call is metered, not invoiced"
    assert costs["free_tier"] == costs["paid"] == EXPECTED_COST


# --- AC-59, second sentence ---------------------------------------------------------------


def _estimate() -> int:
    """The Router estimate, computed here: the padded input plus the output cap, each rounded up."""
    messages, _ = build_generation_messages(INSTRUCTIONS, [])
    units = CharCountEstimator().estimate_messages(messages)
    padded = -(-(units * 110) // 100)  # default context_safety_margin_percent is 10
    return _ceil_cost(padded, IN_PRICE) + _ceil_cost(1500, OUT_PRICE)


def _usd(micro: int) -> str:
    return f"{Decimal(micro) / Decimal(1_000_000):.6f}"


async def test_a_candidate_the_router_passes_is_admitted_at_the_exact_budget_boundary(
    env: AiDbEnv,
) -> None:
    """AC-59: remaining budget equal to the estimate passes Router step 7 (the boundary is
    inclusive) and the reservation of the same amount is admitted against the same snapshot."""
    estimate = _estimate()
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES[:1],
        budget_usd=_usd(estimate),
        script=[ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=10, output_units=5)],
    )
    await orchestrator.run(_ctx(workspace_id), _request())
    (usage,) = await _usage(env, workspace_id)
    assert usage.reserved_micro_usd == estimate and usage.status == "succeeded"
    assert len(provider.calls) == 1


async def test_a_candidate_the_router_removes_is_refused_by_a_reservation_of_that_amount(
    env: AiDbEnv,
) -> None:
    """AC-59: one micro-USD below the estimate, the Router removes the candidate at step 7 and the
    atomic reservation of the same amount against the same budget is refused too."""
    estimate = _estimate()
    assert estimate > 1
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES[:1],
        budget_usd=_usd(estimate - 1),
        script=[ScriptedResponse.ok(VALID_OUTPUT_JSON)],
    )
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert not provider.calls
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "budget_exceeded"
    assert await _usage(env, workspace_id) == []

    other_workspace = await env.new_workspace()
    coordinator = env.coordinator(env.clock(), limit=estimate - 1)
    with pytest.raises(AiBudgetExceeded):
        await env.reserve(coordinator, other_workspace, env.clock(), estimate)


# --- AC-16 ---------------------------------------------------------------------------------------


def _fail(kind: Kind) -> ScriptedResponse:
    return ScriptedResponse.fail(kind, input_units=100, output_units=0)


@pytest.mark.parametrize(
    ("script_item", "code"),
    [
        pytest.param(_fail(Kind.TIMEOUT), "provider_timeout", id="timeout"),
        pytest.param(_fail(Kind.CONNECTION_ERROR), "provider_unavailable", id="connection"),
        pytest.param(_fail(Kind.RATE_LIMITED), "provider_rate_limited", id="rate-limit"),
        pytest.param(_fail(Kind.AUTH_FAILED), "provider_auth_failed", id="auth"),
        pytest.param(
            ScriptedResponse.ok(
                VALID_OUTPUT_JSON, input_units=100, output_units=50, finish_reason="length"
            ),
            "output_truncated",
            id="truncation",
        ),
    ],
)
async def test_when_every_candidate_fails_the_request_carries_the_last_code(
    env: AiDbEnv, script_item: ScriptedResponse, code: str
) -> None:
    """AC-16, spec 10.3: every row of the table that falls back ends, after the cap of three
    distinct models, with ``AiProviderUnavailable`` and the persisted code of the failure; each
    attempt has its own failed ledger row with the same code; nothing is stored."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[script_item] * 4
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len({c.request.model for c in provider.calls}) == len(provider.calls) == 3
    usage = await _usage(env, workspace_id)
    assert [(u.status, u.error_code) for u in usage] == [("failed", code)] * 3
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == code
    assert row.output_payload is None and row.completed_at is not None
