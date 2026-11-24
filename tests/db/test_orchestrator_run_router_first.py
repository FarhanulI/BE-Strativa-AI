"""T-011 step 9: every provider call of ``run`` is preceded by a Router decision (local Postgres).

Covers AC-9 (``run`` part: no provider call without a Router decision) and INV-4 (``run`` path).
A spy replaces the orchestrator module's ``route`` (it records the decision and delegates to the
real Router) and a spy provider records each call into the same ordered event list. For every run
the list must show exactly one Router decision first, then only provider calls whose
(provider, model) is a candidate of that decision; a Router refusal produces no provider call;
a second run gets its own decision before its own calls. Cases: success, repair, fallback,
refusal. Synthetic text only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import text

import app.ai_platform.orchestrator as orchestrator_module
from app.ai_platform import (
    AiCallContext,
    AiProviderNotConfigured,
    AiTaskName,
    AiTaskRequest,
    FakeAiProvider,
    ScriptedResponse,
)
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.ai_platform.provider import ProviderGenerationRequest, ProviderGenerationResponse
from app.ai_platform.router import RoutingResult
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import CHAT_PROVIDER, VALID_OUTPUT_JSON, build_orchestrator
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS
ENTRIES = tuple(
    chat_entry(provider=CHAT_PROVIDER, model=f"synthetic-{name}", latency_p50_ms=500 + 100 * index)
    for index, name in enumerate("abc")
)
BAD = json.dumps({"value": 5})

Event = tuple[str, Any]


class OrderedProvider(FakeAiProvider):
    """Records every call into a shared, ordered event list."""

    def __init__(self, script: list[ScriptedResponse], events: list[Event]) -> None:
        super().__init__(script)
        self._events = events

    async def generate(
        self, request: ProviderGenerationRequest, *, api_key: SecretStr | None
    ) -> ProviderGenerationResponse:
        self._events.append(("provider", (request.provider, request.model)))
        return await super().generate(request, api_key=api_key)


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


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[Event]:
    """The shared event list; ``route`` is wrapped so each Router decision is recorded."""
    recorded: list[Event] = []
    real_route = orchestrator_module.route

    def spy_route(routing_input: Any) -> RoutingResult:
        result = real_route(routing_input)
        recorded.append(("route", result))
        return result

    monkeypatch.setattr(orchestrator_module, "route", spy_route)
    return recorded


def _ok(raw: str = VALID_OUTPUT_JSON) -> ScriptedResponse:
    return ScriptedResponse.ok(raw, input_units=100, output_units=20)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


def _request() -> AiTaskRequest:
    return AiTaskRequest(task=TASK, instructions="synthetic")


async def _run_once(
    env: AiDbEnv, events: list[Event], script: list[ScriptedResponse], *, key: bool = True
) -> int:
    """One ``run``; returns how many events it appended."""
    before = len(events)
    workspace_id = await env.new_workspace()
    provider = OrderedProvider(script, events)
    orchestrator, _ = build_orchestrator(
        env,
        env.clock(),
        entries=ENTRIES,
        provider=provider,
        key="synthetic-test-key-not-real" if key else None,
    )
    try:
        await orchestrator.run(_ctx(workspace_id), _request())
    except AiProviderNotConfigured:
        if key:
            raise
    return len(events) - before


def _assert_router_first(run_events: list[Event], expected_calls: int) -> None:
    kinds = [kind for kind, _ in run_events]
    assert kinds == ["route"] + ["provider"] * expected_calls
    decision: RoutingResult = run_events[0][1]
    assert decision.failure is None
    allowed = {(c.provider, c.model) for c in decision.candidates}
    for _, pair in run_events[1:]:
        assert pair in allowed  # only models the Router chose


async def test_a_successful_run_calls_the_provider_only_after_the_router_decision(
    env: AiDbEnv, events: list[Event]
) -> None:
    """AC-9 (run), INV-4 (run): one Router decision, then the single provider call."""
    appended = await _run_once(env, events, [_ok()])
    assert appended == 2
    _assert_router_first(events, 1)


async def test_repair_and_fallback_calls_are_all_covered_by_the_one_decision(
    env: AiDbEnv, events: list[Event]
) -> None:
    """AC-9 (run), INV-4 (run): a fallback after a failure and a repair after invalid output
    happen after the same single decision and only use models it listed."""
    script = [ScriptedResponse.fail(Kind.TIMEOUT), _ok(BAD), _ok()]  # fail -> invalid -> repair
    appended = await _run_once(env, events, script)
    assert appended == 4
    _assert_router_first(events, 3)
    models = [pair for kind, pair in events[1:] if kind == "provider"]
    assert models[0] != models[1] and models[1] == models[2]  # fallback, then repair, same model


async def test_a_router_refusal_makes_no_provider_call(env: AiDbEnv, events: list[Event]) -> None:
    """AC-9 (run), INV-4 (run): when the Router refuses (no credentials), the provider is never
    called."""
    appended = await _run_once(env, events, [_ok()], key=False)
    assert appended == 1
    assert [kind for kind, _ in events] == ["route"]
    assert events[0][1].failure is not None


async def test_each_run_gets_its_own_decision_before_its_own_calls(
    env: AiDbEnv, events: list[Event]
) -> None:
    """AC-9 (run), INV-4 (run): two runs in a row interleave as route, call, route, call, so a
    decision is never reused for another request."""
    await _run_once(env, events, [_ok()])
    await _run_once(env, events, [_ok()])
    assert [kind for kind, _ in events] == ["route", "provider", "route", "provider"]
    assert events[0][1] is not events[2][1]
