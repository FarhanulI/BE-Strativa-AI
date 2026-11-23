"""T-011 step 4: ``AiOrchestrator.run`` fallback, error mapping and deadline stop (local Postgres).

Covers spec 10.3 (the classification table, fallback in rank order, the attempt cap, terminal
kinds, the deadline stop, ``budget_exceeded`` never falling back), AC-15 (fallback and
``route_rank``), AC-16 (``run`` part: error code, fallback or not, attempt bound per kind), AC-18
(``max_provider_attempts``), AC-19 (the deadline stop with ``FakeClock``) and D-32 (the final
error, observed behavior: D-32 is unresolved, see T-004). Every attempt has its own reservation
and usage row (INV-7). Synthetic text only; the provider is the scripted fake.
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
    AiContentRefused,
    AiOutputInvalid,
    AiProviderUnavailable,
    AiTaskName,
    AiTaskRequest,
    FakeAiProvider,
    ScriptedResponse,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.provider import ProviderGenerationRequest, ProviderGenerationResponse
from app.core import FakeClock, Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import (
    CHAT_PROVIDER,
    VALID_OUTPUT_JSON,
    OutputForTests,
    build_orchestrator,
)
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # interactive: ranked by latency, 20 s deadline
IN_UNITS, OUT_UNITS = 1000, 200
# Four synthetic models, ranked by latency for an interactive task: a, b, c, d.
MODELS = ("synthetic-a", "synthetic-b", "synthetic-c", "synthetic-d")
ENTRIES = tuple(
    chat_entry(provider=CHAT_PROVIDER, model=name, latency_p50_ms=500 + 100 * index)
    for index, name in enumerate(MODELS)
)
BAD_OUTPUT = json.dumps({"value": 5})


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
    return AiTaskRequest(task=TASK, instructions="synthetic instructions")


def _ok(raw: str = VALID_OUTPUT_JSON, **kwargs: Any) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=IN_UNITS, output_units=OUT_UNITS, **kwargs)


def _fail(kind: Kind) -> ScriptedResponse:
    return ScriptedResponse.fail(kind, input_units=IN_UNITS, output_units=0)


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


async def _reserved(env: AiDbEnv, workspace_id: UUID) -> int:
    (row,) = await _rows(
        env,
        "SELECT COALESCE(SUM(reserved_micro_usd), 0) AS r FROM ai_budget_periods "
        "WHERE workspace_id = :w",
        workspace_id,
    )
    return int(row.r)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


@pytest.mark.parametrize(
    ("first", "code"),
    [
        (_fail(Kind.TIMEOUT), "provider_timeout"),
        (_fail(Kind.CONNECTION_ERROR), "provider_unavailable"),
        (_fail(Kind.HTTP_5XX), "provider_unavailable"),
        (_fail(Kind.RATE_LIMITED), "provider_rate_limited"),
        (_fail(Kind.AUTH_FAILED), "provider_auth_failed"),
        (_ok(VALID_OUTPUT_JSON, finish_reason="length"), "output_truncated"),
        (_ok(BAD_OUTPUT), "output_invalid"),
    ],
)
async def test_a_failed_attempt_falls_back_to_the_next_candidate_in_rank_order(
    env: AiDbEnv, first: ScriptedResponse, code: str
) -> None:
    """Spec 10.3, AC-15, AC-16: each fallback kind is settled ``failed`` with its code, the next
    model is tried (rank 2), and the request succeeds with usage summed over both attempts."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[first, _ok()]
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())

    assert isinstance(result.output, OutputForTests)
    assert [c.request.model for c in provider.calls] == [MODELS[0], MODELS[1]]
    first_usage, second_usage = await _usage(env, workspace_id)
    assert (first_usage.attempt_no, first_usage.route_rank) == (1, 1)
    assert first_usage.status == "failed" and first_usage.error_code == code
    assert (second_usage.attempt_no, second_usage.route_rank) == (2, 2)
    assert second_usage.status == "succeeded" and second_usage.error_code is None
    assert (first_usage.model, second_usage.model) == (MODELS[0], MODELS[1])
    assert second_usage.id == result.routing_id and result.usage.call_count == 2
    assert result.usage.input_units == first_usage.input_units + second_usage.input_units
    assert result.usage.cost_micro_usd == first_usage.cost_micro_usd + second_usage.cost_micro_usd
    row = await _request_row(env, workspace_id)
    assert row.status == "succeeded" and row.error_code is None
    assert row.cost_micro_usd == result.usage.cost_micro_usd
    assert await _reserved(env, workspace_id) == 0  # every reservation was released (INV-7)


@pytest.mark.parametrize(
    ("kind", "code", "error"),
    [
        (Kind.BAD_REQUEST, "provider_bad_request", AiProviderUnavailable),
        (Kind.CONTENT_REFUSED, "content_refused", AiContentRefused),
    ],
)
async def test_bad_request_and_content_refusal_make_exactly_one_attempt(
    env: AiDbEnv, kind: Kind, code: str, error: type[Exception]
) -> None:
    """Spec 10.3, AC-16: no fallback although more candidates exist."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_fail(kind), _ok()]
    )
    with pytest.raises(error):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    (usage,) = await _usage(env, workspace_id)
    assert usage.status == "failed" and usage.error_code == code
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == code and row.completed_at is not None
    assert await _reserved(env, workspace_id) == 0


async def test_attempts_stop_at_max_provider_attempts_with_distinct_models(env: AiDbEnv) -> None:
    """Spec 10.3, AC-18: four candidates, every call fails, only three distinct models are tried
    and the request ends with the code of the last failure."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_fail(Kind.HTTP_5XX)] * 4
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == list(MODELS[:3])
    usage = await _usage(env, workspace_id)
    assert [u.attempt_no for u in usage] == [1, 2, 3]
    assert all(u.status == "failed" for u in usage)
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_unavailable"
    assert row.output_payload is None


async def test_all_invalid_outputs_end_with_ai_output_invalid(env: AiDbEnv) -> None:
    """Spec 10.3 / D-32: every attempt invalid -> ``AiOutputInvalid``, code ``output_invalid``.
    No repair call yet (step 6), so one call per model."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES, script=[_ok(BAD_OUTPUT)] * 3
    )
    with pytest.raises(AiOutputInvalid):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 3
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "output_invalid"
    assert row.output_payload is None


async def test_mixed_failures_end_with_the_class_and_code_of_final_error(env: AiDbEnv) -> None:
    """Current behavior, D-32 unresolved (T-004): an invalid output followed by transport
    failures raises ``AiProviderUnavailable`` and persists the last failure's code."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        script=[_ok(BAD_OUTPUT), _fail(Kind.TIMEOUT), _fail(Kind.CONNECTION_ERROR)],
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_unavailable"


async def test_a_single_candidate_that_fails_ends_the_request(env: AiDbEnv) -> None:
    """Fewer candidates than the cap: the candidates run out and the final error applies."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=ENTRIES[:1], script=[_fail(Kind.TIMEOUT)]
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_timeout"


class _ClockMovingProvider(FakeAiProvider):
    """The fake provider, but each call first moves the shared ``FakeClock`` forward."""

    def __init__(self, clock: FakeClock, seconds: list[float], script: list[ScriptedResponse]):
        super().__init__(script)
        self._clock = clock
        self._seconds = seconds

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: Any
    ) -> ProviderGenerationResponse:
        self._clock.advance(timedelta(seconds=self._seconds.pop(0)))
        return await super().generate(request, api_key=api_key)


async def test_the_deadline_stops_the_next_attempt_when_the_time_left_is_below_its_p50(
    env: AiDbEnv,
) -> None:
    """Spec 10.3, AC-19: 19.9 s of the 20 s interactive deadline are gone, the next model needs
    600 ms, so the request fails ``provider_timeout`` and no second call or usage row exists."""
    clock = env.clock()
    workspace_id = await env.new_workspace()
    provider = _ClockMovingProvider(clock, [19.9], [_fail(Kind.TIMEOUT), _ok()])
    orchestrator, _ = build_orchestrator(env, clock, entries=ENTRIES, provider=provider)
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    (usage,) = await _usage(env, workspace_id)
    assert usage.error_code == "provider_timeout"
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_timeout"
    assert await _reserved(env, workspace_id) == 0


async def test_the_deadline_allows_the_next_attempt_when_enough_time_is_left(env: AiDbEnv) -> None:
    """AC-19 counterpart: 19.0 s used leaves 1000 ms, above the next model's 600 ms p50, and the
    second call gets exactly the time that is left as its timeout."""
    clock = env.clock()
    workspace_id = await env.new_workspace()
    provider = _ClockMovingProvider(clock, [19.0, 0.0], [_fail(Kind.TIMEOUT), _ok()])
    orchestrator, _ = build_orchestrator(env, clock, entries=ENTRIES, provider=provider)
    result = await orchestrator.run(_ctx(workspace_id), _request())
    assert result.usage.call_count == 2
    assert provider.calls[1].request.timeout_seconds == pytest.approx(1.0)


class _RefuseSecondReservation(BudgetCoordinator):
    """Lets the first reservation through and refuses the second (the budget moved, 12.3)."""

    _seen = 0

    async def reserve_for_call(self, scope: Any, workspace_id: Any, *args: Any) -> Any:
        self._seen += 1
        if self._seen == 2:
            await self.refuse_for_call(scope, workspace_id, "GENERATE_HOOK_VARIATIONS")
            raise AiBudgetExceeded()
        return await super().reserve_for_call(scope, workspace_id, *args)


async def test_budget_exhaustion_on_a_fallback_attempt_never_falls_back_further(
    env: AiDbEnv,
) -> None:
    """Spec 10.3: ``budget_exceeded`` ends the request; the first attempt stays settled
    ``failed`` and the later candidates are not tried."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        script=[_fail(Kind.HTTP_5XX), _ok(), _ok()],
        coordinator_factory=_RefuseSecondReservation,
    )
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert len(provider.calls) == 1
    (usage,) = await _usage(env, workspace_id)
    assert usage.status == "failed" and usage.error_code == "provider_unavailable"
    row = await _request_row(env, workspace_id)
    assert row.status == "failed" and row.error_code == "budget_exceeded"
    assert await _reserved(env, workspace_id) == 0
