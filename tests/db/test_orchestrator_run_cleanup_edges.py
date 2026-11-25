"""T-024 step 2: the cleanup path of ``AiOrchestrator.run`` after a fault, current behavior (local
Postgres). Tests only; the orchestrator is not changed in this step.

* A cleanup that itself fails (``abandon_call`` raising, the run-level completion raising): the
  original exception still reaches the caller unchanged, nothing is left as an unretrieved task
  exception, and the rows are left in the documented state until the reaper (spec 4.5, 8.2, not
  built) cleans up. INV-7, INV-14, AC-45 (``run`` part).
* A fault in a later attempt (a fallback call, a repair call) after earlier attempts settled: the
  settled attempts keep their cost, the in-flight one is abandoned at its estimate, the budget holds
  no reservation and ``spent`` is the exact sum. INV-7, INV-14.
* A wider content check on the T-023 fault paths (a provider exception, a failure while settling, a
  cancellation): the sentinel is absent from the request, usage and budget rows, from the outbox
  and audit rows of the budget row, from structlog output and from the standard log; the cleanup
  writes no event and no audit row. INV-18, AC-28 (``run`` part).
Synthetic text only.
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, text
from structlog import get_logger
from structlog.testing import capture_logs

from app.ai_platform import AiCallContext, AiTaskName, AiTaskRequest, ScriptedResponse
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.fake_provider import FakeAiProvider
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # default output cap 1500
ORIGINAL = "zz-sentinel-original-8841"  # the exception the caller must see
CLEANUP = "zz-sentinel-cleanup-8842"  # the exception raised by a failing cleanup
SENTINEL = "zz-sentinel-t024-4417"  # content that must never be stored or logged
IN_PRICE, OUT_PRICE = 1_000_000, 600_000  # micro-USD per million units: 1 micro-USD per input unit
ENTRIES = tuple(
    chat_entry(
        provider=CHAT_PROVIDER,
        model=f"synthetic-{name}",
        latency_p50_ms=500 + 100 * index,
        input_micro_usd_per_million_units=IN_PRICE,
        output_micro_usd_per_million_units=OUT_PRICE,
    )
    for index, name in enumerate("ab")
)
BAD = json.dumps({"value": 5, "extra": "zz-sentinel-output-5522"})
IN_UNITS, OUT_UNITS = 1000, 200


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


def _ceil_cost(units: int, price_per_million: int) -> int:
    return -(-(units * price_per_million) // 1_000_000)


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


def _raising(message: str) -> Callable[[Any], ScriptedResponse]:
    def responder(_request: Any) -> ScriptedResponse:
        raise RuntimeError(message)

    return responder


class _AbandonFails(BudgetCoordinator):
    """Abandoning the in-flight reservation raises, as a database error in the cleanup would."""

    async def abandon_call(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(CLEANUP)


class _SettleFails(BudgetCoordinator):
    async def settle_call(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(SENTINEL)


def _assert_no_unretrieved_task_exception(caplog: pytest.LogCaptureFixture) -> None:
    """A dropped cleanup error must be marked retrieved, or asyncio logs it when the task is
    garbage collected."""
    gc.collect()
    assert "never retrieved" not in caplog.text


# --- A cleanup that itself fails (spec 4.5: the reaper is the backstop) ---------------------------


async def test_a_failing_abandon_leaves_the_usage_row_reserved_and_the_caller_sees_the_original(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """INV-7, INV-14, AC-45 (run): ``abandon_call`` raises while cleaning up a provider fault. The
    caller still sees the provider's exception unchanged; the request row is still ended ``failed``
    with ``execution_abandoned``. The usage row stays ``reserved`` and the budget keeps the
    reservation (``spent`` unchanged) until the reaper abandons it (not built: documented open)."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        provider=FakeAiProvider(responder=_raising(ORIGINAL)),
        coordinator_factory=_AbandonFails,
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL and raised.value.__cause__ is None
    assert len(provider.calls) == 1
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"
    (usage,) = await _usage(env, workspace_id)
    assert usage.status == "reserved" and usage.reserved_micro_usd > 0
    budget = await _budget(env, workspace_id)
    assert budget.reserved_micro_usd == usage.reserved_micro_usd and budget.spent_micro_usd == 0
    assert CLEANUP not in caplog.text and ORIGINAL not in caplog.text
    _assert_no_unretrieved_task_exception(caplog)


async def test_a_failing_completion_leaves_the_row_running_and_the_caller_sees_the_original(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """INV-7, INV-14, AC-45 (run): the run-level completion (``UPDATE ai_requests``) raises while
    cleaning up a provider fault. The caller still sees the provider's exception unchanged. The
    in-flight reservation was abandoned before that, so the usage row is ``abandoned`` at its
    estimate and the budget holds no reservation; the request row stays ``running`` until the
    reaper ends it (not built: documented open)."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env, env.clock(), provider=FakeAiProvider(responder=_raising(ORIGINAL))
    )

    def fail_the_completion(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if "UPDATE ai_requests" in statement:
            raise RuntimeError(CLEANUP)

    event.listen(env.engine.sync_engine, "before_cursor_execute", fail_the_completion)
    try:
        with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as raised:
            await orchestrator.run(_ctx(workspace_id), _request())
    finally:
        event.remove(env.engine.sync_engine, "before_cursor_execute", fail_the_completion)
    assert str(raised.value) == ORIGINAL and raised.value.__cause__ is None
    row = await _request_row(env, workspace_id)
    assert row.status == "running" and row.completed_at is None
    (usage,) = await _usage(env, workspace_id)
    assert usage.status == "abandoned" and usage.cost_micro_usd == usage.reserved_micro_usd > 0
    budget = await _budget(env, workspace_id)
    assert budget.reserved_micro_usd == 0 and budget.spent_micro_usd == usage.reserved_micro_usd
    assert CLEANUP not in caplog.text and ORIGINAL not in caplog.text
    _assert_no_unretrieved_task_exception(caplog)


# --- A fault after earlier attempts settled -------------------------------------------------------


async def test_a_fault_in_a_fallback_attempt_keeps_the_settled_attempt_and_abandons_the_new_one(
    env: AiDbEnv,
) -> None:
    """INV-7, INV-14: attempt 1 fails with a counted failure and settles at its metered cost;
    attempt 2 (the next model) raises unexpectedly. Attempt 1 keeps its cost, attempt 2 is
    abandoned at its estimate, the budget holds no reservation and ``spent`` is the exact sum."""
    calls = 0

    def responder(_request: Any) -> ScriptedResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ScriptedResponse.fail(Kind.CONNECTION_ERROR, input_units=100, output_units=0)
        raise RuntimeError(ORIGINAL)

    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, provider=FakeAiProvider(responder=responder)
    )
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL
    assert len({c.request.model for c in provider.calls}) == len(provider.calls) == 2
    first, second = await _usage(env, workspace_id)
    assert (first.status, first.error_code) == ("failed", "provider_unavailable")
    assert first.cost_micro_usd == _ceil_cost(100, IN_PRICE) == 100  # settled at the metered cost
    assert second.status == "abandoned" and second.call_kind == "generation"
    assert second.cost_micro_usd == second.reserved_micro_usd > 0
    budget = await _budget(env, workspace_id)
    assert budget.reserved_micro_usd == 0
    assert budget.spent_micro_usd == first.cost_micro_usd + second.reserved_micro_usd
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"


async def test_a_fault_in_a_repair_call_keeps_the_settled_first_call_and_abandons_the_repair(
    env: AiDbEnv,
) -> None:
    """INV-7, INV-14: the first call returns invalid output and settles ``failed``; the repair call
    (same model, D-34) raises unexpectedly. The first call keeps its cost, the repair reservation is
    abandoned at its estimate, ``reserved`` is 0 and ``spent`` is the exact sum."""
    calls = 0

    def responder(_request: Any) -> ScriptedResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return ScriptedResponse.ok(BAD, input_units=IN_UNITS, output_units=OUT_UNITS)
        raise RuntimeError(ORIGINAL)

    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES[:1], provider=FakeAiProvider(responder=responder)
    )
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL
    assert len({c.request.model for c in provider.calls}) == 1 and len(provider.calls) == 2
    first, repair = await _usage(env, workspace_id)
    assert (first.status, first.error_code, first.call_kind) == (
        "failed",
        "output_invalid",
        "generation",
    )
    assert first.cost_micro_usd == _ceil_cost(IN_UNITS, IN_PRICE) + _ceil_cost(OUT_UNITS, OUT_PRICE)
    assert repair.status == "abandoned" and repair.call_kind == "repair"
    assert repair.cost_micro_usd == repair.reserved_micro_usd > 0
    budget = await _budget(env, workspace_id)
    assert budget.reserved_micro_usd == 0
    assert budget.spent_micro_usd == first.cost_micro_usd + repair.reserved_micro_usd
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "execution_abandoned"


# --- The wider content check ----------------------------------------------------------------------


async def _collect(
    env: AiDbEnv, workspace_id: UUID, caplog: pytest.LogCaptureFixture, records: list[Any]
) -> tuple[dict[str, str], int, int]:
    """Every place content could appear, as text, and the number of outbox and audit rows written
    for the workspace's budget row."""
    places = {"structlog": repr(records), "caplog": caplog.text}
    for table in ("ai_requests", "ai_usage_records", "ai_budget_periods"):
        rows = await _rows(env, f"SELECT * FROM {table} WHERE workspace_id = :w", workspace_id)
        places[table] = json.dumps([[str(v) for v in row] for row in rows])
    outbox = audit = 0
    budget_id = await env.find_budget_row(workspace_id, env.clock())
    if budget_id is not None:
        events, audits = await env.events(budget_id), await env.audits(budget_id)
        places["outbox_events"], places["audit_log"] = repr(events), repr(audits)
        outbox, audit = len(events), len(audits)
    return places, outbox, audit


def _leaks(places: dict[str, str]) -> list[str]:
    return [name for name, content in places.items() if SENTINEL in content]


async def test_the_content_probe_can_fail(env: AiDbEnv, caplog: pytest.LogCaptureFixture) -> None:
    """The probe is not vacuous: a sentinel planted in structlog output and in the standard log is
    found by the same collector the fault tests use."""
    workspace_id = await env.new_workspace()
    with capture_logs() as records, caplog.at_level(logging.DEBUG):
        get_logger().info("t024.planted", detail=SENTINEL)
        logging.getLogger("t024").warning(SENTINEL)
        places, _, _ = await _collect(env, workspace_id, caplog, records)
    assert _leaks(places) == ["structlog", "caplog"]


async def _run_fault(env: AiDbEnv, workspace_id: UUID, kind: str) -> None:
    if kind == "cancel":
        orchestrator, provider = build_orchestrator(
            env, env.clock(), script=[ScriptedResponse.ok(VALID_OUTPUT_JSON, delay_seconds=3600.0)]
        )
        task = asyncio.ensure_future(orchestrator.run(_ctx(workspace_id), _request()))
        for _ in range(500):  # wait until the provider call has started (it is recorded first)
            if provider.calls:
                break
            await asyncio.sleep(0.01)
        assert len(provider.calls) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return
    if kind == "provider":
        orchestrator, _ = build_orchestrator(
            env, env.clock(), provider=FakeAiProvider(responder=_raising(SENTINEL))
        )
    else:
        orchestrator, _ = build_orchestrator(
            env,
            env.clock(),
            script=[ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=100, output_units=20)],
            coordinator_factory=_SettleFails,
        )
    with pytest.raises(RuntimeError):
        await orchestrator.run(_ctx(workspace_id), _request())


@pytest.mark.parametrize("kind", ["provider", "settle", "cancel"])
async def test_a_fault_leaves_no_content_in_any_row_log_event_or_audit_record(
    env: AiDbEnv, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    """INV-18, AC-28 (run): after a provider exception, a failure while settling or a cancellation,
    the sentinel carried by the exception is absent from the request, usage and budget rows, the
    outbox and audit rows of the budget row, structlog output and the standard log, and the cleanup
    wrote no event and no audit row."""
    workspace_id = await env.new_workspace()
    with capture_logs() as records, caplog.at_level(logging.DEBUG):
        await _run_fault(env, workspace_id, kind)
        places, outbox, audit = await _collect(env, workspace_id, caplog, records)
    assert "ai_budget_periods" in places and "outbox_events" in places  # the budget row was probed
    assert _leaks(places) == []
    assert (outbox, audit) == (0, 0)
