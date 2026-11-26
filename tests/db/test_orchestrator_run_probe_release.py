"""T-022 checkpoint 4: ``AiOrchestrator.run`` releases a claimed half-open probe on every path that
records no provider outcome (AC-65, D-37), local Postgres. Registry semantics (AC-64) are covered by
the unit tests and are not repeated here. Synthetic text only.

Setup: the breaker of the only model is opened with five counted failures, then the fake clock moves
past the open period, so the next attempt claims the half-open probe. A path that records no
provider outcome must release the claim without closing or re-opening the breaker, and the original
exception must reach the caller unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
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
from app.ai_platform.circuit_breaker import AttemptHandle, CircuitBreakerRegistry
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.fake_provider import FakeAiProvider
from app.core import FakeClock, Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import (
    CHAT_PROVIDER,
    VALID_OUTPUT_JSON,
    build_orchestrator,
)
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
MODEL = "synthetic-a"
KEY = (CHAT_PROVIDER, MODEL)
ENTRIES = (chat_entry(provider=CHAT_PROVIDER, model=MODEL),)
ORIGINAL = "zz-sentinel-original-6631"
CLEANUP = "zz-sentinel-cleanup-6632"


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


def _raising(message: str) -> Any:
    def responder(_request: Any) -> ScriptedResponse:
        raise RuntimeError(message)

    return responder


class _Breaker(CircuitBreakerRegistry):
    """The real registry; ``fail_release`` makes ``abandon_attempt`` raise before doing anything."""

    fail_release = False

    def abandon_attempt(self, handle: AttemptHandle) -> None:
        if self.fail_release:
            raise RuntimeError(CLEANUP)
        super().abandon_attempt(handle)


class _Rig:
    """One orchestrator whose breaker for ``MODEL`` is half-open with no probe claimed."""

    def __init__(self) -> None:
        self.breaker: _Breaker | None = None

    def factory(self, clock: Any, config: Any) -> _Breaker:
        self.breaker = _Breaker(clock, config)
        return self.breaker

    def open_then_half_open(self, clock: FakeClock) -> _Breaker:
        assert self.breaker is not None
        for _ in range(20):  # more than any threshold; stops when the breaker opens
            if self.breaker.state(KEY) == "open":
                break
            handle = self.breaker.begin_attempt(KEY)
            assert handle is not None
            self.breaker.record_failure(handle, Kind.TIMEOUT)
        assert self.breaker.state(KEY) == "open"
        clock.advance(timedelta(hours=1))  # beyond any open period, within no lease
        assert self.breaker.state(KEY) == "half_open"
        return self.breaker


def _probe_is_free(breaker: CircuitBreakerRegistry) -> bool:
    """True when no probe claim is held: the next attempt can claim the probe. Claims it."""
    handle = breaker.begin_attempt(KEY)
    return handle is not None and handle.probe


class _RefusingReserve(BudgetCoordinator):
    async def reserve_for_call(self, *args: Any, **kwargs: Any) -> Any:
        raise AiBudgetExceeded()


class _SettleFails(BudgetCoordinator):
    async def settle_call(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(ORIGINAL)


async def test_a_budget_refusal_releases_the_probe_and_is_not_a_provider_failure(
    env: AiDbEnv,
) -> None:
    """AC-65, D-37 (test 10): the reservation is refused while the half-open probe is claimed. The
    probe is released, the breaker stays half-open (nothing re-opened or closed), and no provider
    call was made."""
    rig, clock = _Rig(), env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        clock,
        entries=ENTRIES,
        breaker_factory=rig.factory,
        coordinator_factory=_RefusingReserve,
    )
    breaker = rig.open_then_half_open(clock)
    with pytest.raises(AiBudgetExceeded):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert not provider.calls
    assert breaker.state(KEY) == "half_open"
    assert _probe_is_free(breaker)


async def test_an_unexpected_provider_exception_releases_the_probe_and_propagates(
    env: AiDbEnv,
) -> None:
    """AC-65, D-37 (test 11): a non-provider exception during the probe call releases the claim,
    is not recorded as a provider failure (the breaker stays half-open), and reaches the caller
    unchanged."""
    rig, clock = _Rig(), env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        clock,
        entries=ENTRIES,
        breaker_factory=rig.factory,
        provider=FakeAiProvider(responder=_raising(ORIGINAL)),
    )
    breaker = rig.open_then_half_open(clock)
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL and raised.value.__cause__ is None
    assert len(provider.calls) == 1
    assert breaker.state(KEY) == "half_open"
    assert _probe_is_free(breaker)


@pytest.mark.parametrize(
    ("response", "expected_state"),
    [
        (ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=100, output_units=20), "closed"),
        (ScriptedResponse.fail(Kind.TIMEOUT, input_units=100, output_units=0), "open"),
    ],
    ids=["success", "counted-failure"],
)
async def test_a_settlement_failure_leaves_the_breaker_as_the_recorded_outcome_made_it(
    env: AiDbEnv, response: ScriptedResponse, expected_state: str
) -> None:
    """AC-65, D-37 (test 12): the provider outcome is recorded before settlement, so a settlement
    failure afterwards leaves the breaker as that outcome made it (a probe success closes it, a
    counted probe failure re-opens it), and the cleanup release does not undo that."""
    rig, clock = _Rig(), env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env,
        clock,
        entries=ENTRIES,
        breaker_factory=rig.factory,
        coordinator_factory=_SettleFails,
        script=[response],
    )
    breaker = rig.open_then_half_open(clock)
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL
    assert breaker.state(KEY) == expected_state


async def test_a_failing_release_does_not_replace_the_original_exception(env: AiDbEnv) -> None:
    """AC-65, D-37 (test 13): ``abandon_attempt`` raises while the original exception propagates.
    The caller still sees the original exception, and the request row is still ended ``failed``
    with ``execution_abandoned``. The probe claim is then held until its lease expires (the
    documented backstop), so the breaker admits no second probe meanwhile."""
    rig, clock = _Rig(), env.clock()
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env,
        clock,
        entries=ENTRIES,
        breaker_factory=rig.factory,
        provider=FakeAiProvider(responder=_raising(ORIGINAL)),
    )
    breaker = rig.open_then_half_open(clock)
    breaker.fail_release = True
    with pytest.raises(RuntimeError) as raised:
        await orchestrator.run(_ctx(workspace_id), _request())
    assert str(raised.value) == ORIGINAL and raised.value.__cause__ is None
    async with env.sessions() as session, session.begin():
        row = (
            await session.execute(
                text("SELECT status, error_code FROM ai_requests WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
        ).one()
    assert row.status == "failed" and row.error_code == "execution_abandoned"
    breaker.fail_release = False
    assert breaker.begin_attempt(KEY) is None  # the lost release holds the probe until the lease
