"""T-011 step 6: ``AiOrchestrator.run`` repair, truncation and the call cap (local Postgres).

Covers spec 11 (strict validation, the repair policy), D-34 (the repair reservation: a new one from
the repair messages, skipped over the cost-class ceiling, refused -> ``budget_exceeded`` through
D-33), AC-23 (one repair call to the same model, recorded and reserved), AC-24 (a valid repair
succeeds; an invalid one fails the candidate, the next is tried, ``AiOutputInvalid`` after all,
money kept), AC-25 (truncation is not repaired), AC-27 and INV-9 (at most 6 calls with defaults),
INV-8 (invalid output is never returned or stored) and INV-7 (every reservation settled once).
The invalid output is carried into the repair message as delimited data; the stored rows hold
counts and type names only. Synthetic text only; the provider is the scripted fake.
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
    AiOutputInvalid,
    AiTaskName,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.messages import build_generation_messages
from app.ai_platform.pricing import cost_micro_usd
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.char_estimator import CharCountEstimator
from tests.helpers.orchestrator_db import (
    CHAT_PROVIDER,
    VALID_OUTPUT_JSON,
    OutputForTests,
    build_orchestrator,
)
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # interactive, low cost class, output cap 1500
INSTRUCTIONS = "synthetic instructions"
IN_UNITS, OUT_UNITS = 1000, 200
IN_PRICE, OUT_PRICE = 1_000_000, 600_000  # one micro-USD per input unit: repair costs show clearly
ENTRIES = tuple(
    chat_entry(
        provider=CHAT_PROVIDER,
        model=f"synthetic-{name}",
        latency_p50_ms=500 + 100 * index,
        input_micro_usd_per_million_units=IN_PRICE,
        output_micro_usd_per_million_units=OUT_PRICE,
    )
    for index, name in enumerate("abcd")
)
MODELS = tuple(entry["model"] for entry in ENTRIES)
BAD = json.dumps({"value": 5, "extra": "zz-sentinel-output-5521"})


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


def _request() -> AiTaskRequest:
    return AiTaskRequest(task=TASK, instructions=INSTRUCTIONS)


def _ok(raw: str = VALID_OUTPUT_JSON, **kwargs: Any) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=IN_UNITS, output_units=OUT_UNITS, **kwargs)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


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


async def _budget(env: AiDbEnv, workspace_id: UUID) -> Any:
    (row,) = await _rows(
        env,
        "SELECT reserved_micro_usd, spent_micro_usd FROM ai_budget_periods WHERE workspace_id = :w",
        workspace_id,
    )
    return row


def _estimate(messages: Any) -> int:
    """The reservation of a call, computed independently of the orchestrator (spec 12.2)."""
    units = CharCountEstimator().estimate_messages(messages)
    padded = -(-(units * 110) // 100)  # default context_safety_margin_percent is 10
    return cost_micro_usd(padded, IN_PRICE) + cost_micro_usd(1500, OUT_PRICE)


@pytest.mark.parametrize(
    "invalid",
    [
        pytest.param(json.dumps({"value": 5}), id="wrong-type"),
        pytest.param(json.dumps({"value": "x", "extra": 1}), id="extra-key"),
        pytest.param("this is not json", id="not-json"),
    ],
)
async def test_an_invalid_output_gets_one_repair_call_to_the_same_model(
    env: AiDbEnv, invalid: str
) -> None:
    """AC-23, AC-24: strict validation fails, one repair call goes to the same model
    (``call_kind='repair'``) as its own recorded reservation, and a valid repair succeeds."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_ok(invalid), _ok()]
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())

    assert isinstance(result.output, OutputForTests) and result.output.value == "ok"
    assert [c.request.model for c in provider.calls] == [MODELS[0], MODELS[0]]
    first, repair = await _usage(env, workspace_id)
    assert (first.call_kind, first.attempt_no, first.route_rank) == ("generation", 1, 1)
    assert first.status == "failed" and first.error_code == "output_invalid"
    assert first.schema_valid is False
    assert (repair.call_kind, repair.attempt_no, repair.route_rank) == ("repair", 2, 1)
    assert repair.status == "succeeded" and repair.model == first.model
    assert result.usage.call_count == 2 and result.routing_id == repair.id
    assert result.usage.cost_micro_usd == first.cost_micro_usd + repair.cost_micro_usd
    row = await _request_row(env, workspace_id)
    assert row.status == "succeeded" and row.cost_micro_usd == result.usage.cost_micro_usd
    budget = await _budget(env, workspace_id)
    assert (budget.reserved_micro_usd, budget.spent_micro_usd) == (0, row.cost_micro_usd)


async def test_the_repair_message_and_reservation_follow_the_spec(env: AiDbEnv) -> None:
    """Spec 11, D-34: the repair carries the original messages, the invalid output as delimited
    data and the error locations and types; its reservation is computed from those messages and
    the same output cap, and differs from the first call's (D-24)."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_ok(BAD), _ok()]
    )
    await orchestrator.run(_ctx(workspace_id), _request())

    first_call, repair_call = provider.calls
    original, _ = build_generation_messages(INSTRUCTIONS, [])
    assert repair_call.request.messages[: len(original)] == original  # original request unchanged
    carried, instruction = repair_call.request.messages[-2:]
    assert carried.role == "assistant" and "zz-sentinel-output-5521" in carried.content
    assert instruction.role == "user"
    assert "value: string_type" in instruction.content
    # An unexpected key is model-chosen text, so the validator redacts its name to "?".
    assert "?: extra_forbidden" in instruction.content
    assert "extra:" not in instruction.content
    assert "zz-sentinel-output-5521" not in instruction.content  # locations and types only
    assert repair_call.request.max_output_units == first_call.request.max_output_units == 1500
    assert repair_call.request.model == first_call.request.model

    first, repair = await _usage(env, workspace_id)
    assert first.reserved_micro_usd == _estimate(first_call.request.messages)
    assert repair.reserved_micro_usd == _estimate(repair_call.request.messages)
    assert repair.reserved_micro_usd > first.reserved_micro_usd
    stored = json.dumps([[str(v) for v in usage] for usage in (first, repair)], default=str)
    assert "zz-sentinel-output-5521" not in stored  # counts and type names only
    assert sorted(first.validation_error_types) == ["extra_forbidden", "string_type"]


async def test_an_invalid_repair_fails_the_candidate_and_the_next_one_starts_fresh(
    env: AiDbEnv,
) -> None:
    """AC-24: the repair is invalid too, so model A fails and model B gets a fresh first call."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_ok(BAD), _ok(BAD), _ok()]
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [MODELS[0], MODELS[0], MODELS[1]]
    usage = await _usage(env, workspace_id)
    assert [(u.call_kind, u.attempt_no, u.route_rank, u.status) for u in usage] == [
        ("generation", 1, 1, "failed"),
        ("repair", 2, 1, "failed"),
        ("generation", 3, 2, "succeeded"),
    ]
    assert result.usage.call_count == 3
    # B's first call is a plain generation call: no repair message in it.
    assert all(m.role != "assistant" for m in provider.calls[2].request.messages)


async def test_all_candidates_invalid_ends_ai_output_invalid_and_keeps_the_money(
    env: AiDbEnv,
) -> None:
    """AC-24, AC-27, INV-9, INV-8: an always-invalid provider is limited to
    3 models x (1 + 1 repair) = 6 calls; no output is stored; every call has a ledger row and the
    spend is kept."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_ok(BAD)] * 10
    )
    with pytest.raises(AiOutputInvalid):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [m for m in MODELS[:3] for _ in (0, 1)]
    usage = await _usage(env, workspace_id)
    assert [u.call_kind for u in usage] == ["generation", "repair"] * 3
    assert all(u.status == "failed" and u.error_code == "output_invalid" for u in usage)
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "output_invalid"
    assert row.output_payload is None
    assert row.cost_micro_usd == sum(u.cost_micro_usd for u in usage) > 0
    budget = await _budget(env, workspace_id)
    assert (budget.reserved_micro_usd, budget.spent_micro_usd) == (0, row.cost_micro_usd)


async def test_a_truncated_output_is_not_repaired_and_falls_back(env: AiDbEnv) -> None:
    """AC-25: ``finish_reason='length'`` is ``output_truncated``, no repair call is made and the
    next candidate gets a fresh first call."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        script=[_ok(VALID_OUTPUT_JSON, finish_reason="length"), _ok()],
    )
    await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [MODELS[0], MODELS[1]]
    first, second = await _usage(env, workspace_id)
    assert (first.call_kind, first.error_code, first.finish_reason) == (
        "generation",
        "output_truncated",
        "length",
    )
    assert second.call_kind == "generation" and second.status == "succeeded"


async def test_a_repair_over_the_cost_ceiling_is_skipped_without_a_call(env: AiDbEnv) -> None:
    """D-34: the repair reservation exceeds the task's cost-class ceiling, so there is no repair
    call and no reservation; the candidate counts as failed and the next one is tried. The first
    call still fits, because the ceiling equals its Router estimate."""
    workspace_id = await env.new_workspace()
    messages, _ = build_generation_messages(INSTRUCTIONS, [])
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        config_values={"cost_ceiling_low_micro_usd": _estimate(messages)},
        script=[_ok(BAD), _ok()],
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [MODELS[0], MODELS[1]]
    usage = await _usage(env, workspace_id)
    assert [u.call_kind for u in usage] == ["generation", "generation"]
    assert usage[0].error_code == "output_invalid" and result.usage.call_count == 2


class _RefuseRepairReservation(BudgetCoordinator):
    """Lets generation reservations through and refuses a repair reservation (the budget moved)."""

    async def reserve_for_call(
        self, scope: Any, workspace_id: Any, amount: Any, params: Any
    ) -> Any:
        if params.call_kind == "repair":
            await self.refuse_for_call(scope, workspace_id, params.task)
            raise AiBudgetExceeded()
        return await super().reserve_for_call(scope, workspace_id, amount, params)


async def test_a_refused_repair_reservation_fails_budget_exceeded_with_no_fallback(
    env: AiDbEnv,
) -> None:
    """D-34, D-33: the atomic reservation of the repair is refused -> ``budget_exceeded``; the
    first attempt stays settled ``failed`` and no further candidate is tried."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        script=[_ok(BAD), _ok(), _ok()],
        coordinator_factory=_RefuseRepairReservation,
    )
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    (usage,) = await _usage(env, workspace_id)
    assert usage.call_kind == "generation" and usage.error_code == "output_invalid"
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "budget_exceeded"
    assert row.output_payload is None
    budget = await _budget(env, workspace_id)
    assert budget.reserved_micro_usd == 0
