"""T-011 step 5: ``AiOrchestrator.run`` billing-mode constraint and breaker denial (local Postgres).

Covers INV-29 and AC-17 (``run`` part: a quota-exhausted ``free_tier`` call never falls back to a
``paid`` model, a ``paid`` first choice never falls back to ``free_tier``, excluded candidates carry
``billing_mode`` in the stored snapshot, all rows of one request share one mode, the mode follows
configuration), D-35 (a candidate the breaker denies at call time is skipped: no attempt, no
reservation, no usage row, ``provider_unavailable`` when all are skipped) and the breaker side of
spec 10.3 and 10.4 (outcomes are recorded and an open model is not routed). The chat providers are
``gemini`` (``free_tier`` unless configured otherwise) and ``perplexity`` (always ``paid``), with
synthetic model names. Synthetic text only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from app.ai_platform import (
    AiCallContext,
    AiProviderUnavailable,
    AiTaskName,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform.circuit_breaker import AttemptHandle, CircuitBreakerRegistry
from app.ai_platform.failure_policy import ProviderFailureKind as Kind
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import (
    CHAT_PROVIDER,
    SYNTHETIC_KEY,
    VALID_OUTPUT_JSON,
    build_orchestrator,
)
from tests.helpers.synthetic_catalog import chat_entry

pytestmark = pytest.mark.db

TASK = AiTaskName.GENERATE_HOOK_VARIATIONS  # interactive: ranked by latency
PAID_PROVIDER = "perplexity"  # always ``paid`` in configuration (spec 10.1)
KEYS = {"perplexity_api_key": SYNTHETIC_KEY}


def _gemini(name: str, latency: int) -> dict[str, Any]:
    return chat_entry(provider=CHAT_PROVIDER, model=name, latency_p50_ms=latency)


def _paid(name: str, latency: int) -> dict[str, Any]:
    return chat_entry(provider=PAID_PROVIDER, model=name, latency_p50_ms=latency)


# Two free_tier models then one paid model, ranked a, b, c.
MIXED = (_gemini("synthetic-a", 500), _gemini("synthetic-b", 600), _paid("synthetic-c", 700))
# The same, with the paid model ranked first.
PAID_FIRST = (_gemini("synthetic-a", 500), _gemini("synthetic-b", 600), _paid("synthetic-c", 300))
# Four free_tier models for the breaker tests, ranked a, b, c, d.
FOUR = tuple(_gemini(f"synthetic-{n}", 500 + 100 * i) for i, n in enumerate("abcd"))


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


def _ok() -> ScriptedResponse:
    return ScriptedResponse.ok(VALID_OUTPUT_JSON, input_units=1000, output_units=200)


def _fail(kind: Kind) -> ScriptedResponse:
    return ScriptedResponse.fail(kind, input_units=1000, output_units=0)


def _ctx(workspace_id: UUID) -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=workspace_id, request_id="r")


async def _rows(env: AiDbEnv, sql: str, workspace_id: UUID) -> list[Any]:
    async with env.sessions() as session, session.begin():
        return list((await session.execute(text(sql), {"w": workspace_id})).all())


async def _usage(env: AiDbEnv, workspace_id: UUID) -> list[Any]:
    return await _rows(
        env,
        "SELECT * FROM ai_usage_records WHERE workspace_id = :w ORDER BY created_at, attempt_no",
        workspace_id,
    )


async def _requests(env: AiDbEnv, workspace_id: UUID) -> list[Any]:
    return await _rows(env, "SELECT * FROM ai_requests WHERE workspace_id = :w", workspace_id)


async def _reserved(env: AiDbEnv, workspace_id: UUID) -> int:
    (row,) = await _rows(
        env,
        "SELECT COALESCE(SUM(reserved_micro_usd), 0) AS r FROM ai_budget_periods "
        "WHERE workspace_id = :w",
        workspace_id,
    )
    return int(row.r)


# --- billing mode (INV-29, AC-17) ---------------------------------------------------------------


async def test_a_rate_limited_free_tier_call_falls_back_only_to_free_tier(env: AiDbEnv) -> None:
    """AC-17: A is rate limited, the call falls back to B and never to the paid C. The stored
    snapshot lists C as ineligible with reason ``billing_mode``; every row has one mode."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=MIXED,
        config_values=KEYS,
        script=[_fail(Kind.RATE_LIMITED), _ok()],
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == ["synthetic-a", "synthetic-b"]
    usage = await _usage(env, workspace_id)
    assert [u.error_code for u in usage] == ["provider_rate_limited", None]
    assert {u.billing_mode for u in usage} == {"free_tier"}
    snapshot = {e["model"]: e for e in usage[0].candidate_snapshot}
    assert snapshot["synthetic-c"]["eligible"] is False
    assert snapshot["synthetic-c"]["reason_code"] == "billing_mode"
    assert snapshot["synthetic-a"]["eligible"] is True
    assert result.usage.call_count == 2


async def test_when_all_free_tier_candidates_fail_the_paid_model_is_never_called(
    env: AiDbEnv,
) -> None:
    """AC-17: A and B both fail, ``AiProviderUnavailable`` is raised, C is never called and no
    usage row is ``paid``."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=MIXED,
        config_values=KEYS,
        script=[_fail(Kind.RATE_LIMITED), _fail(Kind.HTTP_5XX), _ok()],
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == ["synthetic-a", "synthetic-b"]
    usage = await _usage(env, workspace_id)
    assert len(usage) == 2 and all(u.billing_mode != "paid" for u in usage)
    (row,) = await _requests(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_unavailable"


async def test_a_paid_first_choice_never_falls_back_to_free_tier(env: AiDbEnv) -> None:
    """AC-17 (reversed order): the paid model ranks first, so only paid candidates are used and
    the free_tier models carry reason ``billing_mode``."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=PAID_FIRST,
        config_values=KEYS,
        script=[_fail(Kind.HTTP_5XX), _ok(), _ok()],
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == ["synthetic-c"]
    (usage,) = await _usage(env, workspace_id)
    assert usage.billing_mode == "paid"
    snapshot = {e["model"]: e for e in usage.candidate_snapshot}
    assert snapshot["synthetic-a"]["reason_code"] == "billing_mode"
    assert snapshot["synthetic-b"]["reason_code"] == "billing_mode"


async def test_the_billing_mode_of_a_model_follows_configuration(env: AiDbEnv) -> None:
    """AC-17: the same model is recorded ``paid`` when its provider is configured ``paid``."""
    workspace_id = await env.new_workspace()
    orchestrator, _ = build_orchestrator(
        env,
        env.clock(),
        entries=FOUR[:1],
        config_values={"gemini_billing_mode": "paid"},
        script=[_ok()],
    )
    await orchestrator.run(_ctx(workspace_id), _request())
    (usage,) = await _usage(env, workspace_id)
    assert usage.billing_mode == "paid"


# --- breaker denial at call time (D-35) ---------------------------------------------------------


class _DenyingBreaker(CircuitBreakerRegistry):
    """Routing still sees the models as available, but ``begin_attempt`` denies some of them:
    the breaker state changed after routing (D-35)."""

    denied: frozenset[tuple[str, str]] = frozenset()

    def begin_attempt(self, key: tuple[str, str]) -> AttemptHandle | None:
        return None if key in self.denied else super().begin_attempt(key)


def _denying(*models: str) -> Any:
    denied = frozenset((CHAT_PROVIDER, m) for m in models)

    def factory(clock: Any, config: Any) -> _DenyingBreaker:
        breaker = _DenyingBreaker(clock, config)
        breaker.denied = denied
        return breaker

    return factory


async def test_a_denied_candidate_is_skipped_without_an_attempt_or_a_ledger_row(
    env: AiDbEnv,
) -> None:
    """D-35: A is denied, B serves the call as attempt 1 with route rank 2; there is no usage
    row, reservation or provider call for A."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=FOUR,
        breaker_factory=_denying("synthetic-a"),
        script=[_ok()],
    )
    result = await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == ["synthetic-b"]
    (usage,) = await _usage(env, workspace_id)
    assert (usage.model, usage.attempt_no, usage.route_rank) == ("synthetic-b", 1, 2)
    assert result.usage.call_count == 1
    assert await _reserved(env, workspace_id) == 0


async def test_skipped_candidates_do_not_use_up_the_attempt_cap(env: AiDbEnv) -> None:
    """D-35, AC-19 bound: A is skipped, so B, C and D are all attempted (three attempts)."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=FOUR,
        breaker_factory=_denying("synthetic-a"),
        script=[_fail(Kind.HTTP_5XX)] * 3,
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [
        "synthetic-b",
        "synthetic-c",
        "synthetic-d",
    ]
    usage = await _usage(env, workspace_id)
    assert [(u.attempt_no, u.route_rank) for u in usage] == [(1, 2), (2, 3), (3, 4)]


async def test_every_candidate_denied_fails_provider_unavailable_with_no_ledger_row(
    env: AiDbEnv,
) -> None:
    """D-35: all remaining candidates skipped -> ``provider_unavailable``; no call, no usage row,
    no reservation, the request row ends ``failed``."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=FOUR[:2],
        breaker_factory=_denying("synthetic-a", "synthetic-b"),
        script=[_ok()],
    )
    with pytest.raises(AiProviderUnavailable):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert provider.calls == () and await _usage(env, workspace_id) == []
    (row,) = await _requests(env, workspace_id)
    assert row.status == "failed" and row.error_code == "provider_unavailable"
    assert row.completed_at is not None and await _reserved(env, workspace_id) == 0


# --- outcomes are recorded on the breaker (spec 10.3, 10.4) -------------------------------------


async def test_an_auth_failure_marks_the_model_unavailable_and_it_is_no_longer_routed(
    env: AiDbEnv,
) -> None:
    """Spec 10.3: auth failure falls back and marks the model unavailable for the process, so the
    next request goes straight to the next model."""
    created: list[CircuitBreakerRegistry] = []

    def factory(clock: Any, config: Any) -> CircuitBreakerRegistry:
        created.append(CircuitBreakerRegistry(clock, config))
        return created[0]

    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        entries=FOUR,
        breaker_factory=factory,
        script=[_fail(Kind.AUTH_FAILED), _ok(), _ok()],
    )
    await orchestrator.run(_ctx(workspace_id), _request())
    assert created[0].state((CHAT_PROVIDER, "synthetic-a")) == "open"
    await orchestrator.run(_ctx(workspace_id), _request())
    assert [c.request.model for c in provider.calls] == [
        "synthetic-a",
        "synthetic-b",
        "synthetic-b",
    ]


async def test_repeated_transient_failures_open_the_breaker_and_routing_skips_the_model(
    env: AiDbEnv,
) -> None:
    """Spec 10.4: five consecutive transient failures inside the window open the breaker; the
    next request is routed past the open model."""
    created: list[CircuitBreakerRegistry] = []

    def factory(clock: Any, config: Any) -> CircuitBreakerRegistry:
        created.append(CircuitBreakerRegistry(clock, config))
        return created[0]

    workspace_id = await env.new_workspace()
    script = [_fail(Kind.TIMEOUT), _ok()] * 5 + [_ok()]
    orchestrator, provider = build_orchestrator(
        env, env.clock(), entries=FOUR, breaker_factory=factory, script=script
    )
    for _ in range(5):
        await orchestrator.run(_ctx(workspace_id), _request())
    assert created[0].state((CHAT_PROVIDER, "synthetic-a")) == "open"
    await orchestrator.run(_ctx(workspace_id), _request())
    assert provider.calls[-1].request.model == "synthetic-b"
    assert [c.request.model for c in provider.calls[:10]] == ["synthetic-a", "synthetic-b"] * 5
    assert len(provider.calls) == 11
