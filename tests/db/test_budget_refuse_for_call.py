"""Database tests for ``BudgetCoordinator.refuse_for_call`` (ai_platform step 5b-1, D-33).

A refusal detected without a reservation attempt (the Router's snapshot step 7) is recorded through
the same refusal transaction as the reserve-failure path: flag, ``ai.budget_exhausted`` at most once
per budget row and period, audit record. It writes no usage row, makes no reservation and does not
raise. Isolation and teardown rules are in ``tests/helpers/ai_request_db_env.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest

from app.ai_platform import budget_repository as repo
from app.ai_platform.errors import AiBudgetExceeded
from app.core import Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env

pytestmark = pytest.mark.db

TIMEOUT_SECONDS = 60
LIMIT = 1_000
SCOPES: list[repo.Scope] = ["workspace", "system"]

EVENT_KEYS = {
    "scope",
    "period_start",
    "threshold_percent",
    "limit_micro_usd",
    "spent_micro_usd",
    "reserved_micro_usd",
}
AUDIT_KEYS = EVENT_KEYS | {"budget_row_id"}


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[AiDbEnv]:
    environment = build_env(migrated_test_schema)
    try:
        yield environment
    finally:
        try:
            await environment.cleanup()
        finally:
            await environment.engine.dispose()


def _task(scope: repo.Scope) -> str:
    return "EMBED_TEXT" if scope == "system" else "GENERATE_HOOK_VARIATIONS"


async def _workspace_for(env: AiDbEnv, scope: repo.Scope) -> UUID | None:
    return await env.new_workspace() if scope == "workspace" else None


async def _gather(*awaitables: Any) -> list[Any]:
    async with asyncio.timeout(TIMEOUT_SECONDS):
        return list(await asyncio.gather(*awaitables, return_exceptions=True))


@pytest.mark.parametrize("scope", SCOPES)
async def test_first_refusal_publishes_exactly_one_event_and_one_audit_record(
    env: AiDbEnv, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(
        coordinator, workspace_id, clock, LIMIT
    )  # the row is now at its limit
    assert await env.events(row_id) == [] and await env.audits(row_id) == []

    assert await coordinator.refuse_for_call(scope, workspace_id, _task(scope)) is None

    events, audits = await env.events(row_id), await env.audits(row_id)
    assert len(events) == 1 and len(audits) == 1
    event, audit = events[0], audits[0]
    assert event.event_type == "ai.budget_exhausted" and event.event_version == 1
    assert event.aggregate_type == "ai_budget" and event.workspace_id == workspace_id
    payload = event.payload
    assert set(payload) == EVENT_KEYS
    assert payload["scope"] == scope and payload["threshold_percent"] == 100
    assert payload["period_start"] == repo.period_start_for(clock.now()).isoformat()
    assert payload["limit_micro_usd"] == LIMIT
    assert payload["spent_micro_usd"] == 0 and payload["reserved_micro_usd"] == LIMIT
    assert audit.action == "ai.budget.exhausted" and audit.actor_type == "system"
    assert audit.resource_type == "ai_budget" and audit.resource_id == str(row_id)
    assert audit.workspace_id == workspace_id and audit.event_id == event.event_id
    assert set(audit.details) == AUDIT_KEYS and audit.details["budget_row_id"] == str(row_id)

    snapshot = await env.budget_row(row_id)
    assert snapshot.exhausted_notified_at is not None
    assert snapshot.reserved_micro_usd == LIMIT and snapshot.spent_micro_usd == 0


@pytest.mark.parametrize("scope", SCOPES)
async def test_repeated_and_concurrent_refusals_publish_nothing_more(
    env: AiDbEnv, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(coordinator, workspace_id, clock, LIMIT)

    await coordinator.refuse_for_call(scope, workspace_id, _task(scope))
    for _ in range(2):
        await coordinator.refuse_for_call(scope, workspace_id, _task(scope))
    outcomes = await _gather(
        *(coordinator.refuse_for_call(scope, workspace_id, _task(scope)) for _ in range(25))
    )
    assert outcomes == [None] * 25

    assert len(await env.events(row_id)) == 1
    assert len(await env.audits(row_id)) == 1


@pytest.mark.parametrize("scope", SCOPES)
async def test_concurrent_first_refusals_publish_once(env: AiDbEnv, scope: repo.Scope) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(coordinator, workspace_id, clock, LIMIT)

    outcomes = await _gather(
        *(coordinator.refuse_for_call(scope, workspace_id, _task(scope)) for _ in range(30))
    )
    assert outcomes == [None] * 30
    assert len(await env.events(row_id)) == 1
    assert len(await env.audits(row_id)) == 1


@pytest.mark.parametrize("scope", SCOPES)
async def test_a_refusal_writes_no_usage_row_and_reserves_nothing(
    env: AiDbEnv, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    coordinator = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(coordinator, workspace_id, clock, 600)
    usage_before = await env.usage_count()

    await coordinator.refuse_for_call(scope, workspace_id, _task(scope))

    assert await env.usage_count() == usage_before == 1
    snapshot = await env.budget_row(row_id)
    assert snapshot.reserved_micro_usd == 600 and snapshot.spent_micro_usd == 0
    # The event reports the amounts that actually hold, not the limit.
    (event,) = await env.events(row_id)
    assert event.payload["reserved_micro_usd"] == 600
    assert event.payload["spent_micro_usd"] == 0


@pytest.mark.parametrize("scope", SCOPES)
async def test_a_refusal_creates_the_budget_row_when_none_exists_yet(
    env: AiDbEnv, scope: repo.Scope
) -> None:
    clock = env.clock()
    workspace_id = await _workspace_for(env, scope)
    assert await env.find_budget_row(workspace_id, clock) is None
    coordinator = env.coordinator(clock, LIMIT)

    await coordinator.refuse_for_call(scope, workspace_id, _task(scope))

    row_id = await env.find_budget_row(workspace_id, clock)
    assert row_id is not None
    snapshot = await env.budget_row(row_id)
    assert snapshot.limit_micro_usd == LIMIT
    assert snapshot.reserved_micro_usd == 0 and snapshot.spent_micro_usd == 0
    assert snapshot.exhausted_notified_at is not None
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1
    assert await env.usage_count() == 0


@pytest.mark.parametrize("scope", SCOPES)
async def test_refuse_for_call_has_the_same_event_semantics_as_the_reserve_failure_path(
    env: AiDbEnv, scope: repo.Scope
) -> None:
    # Two equal budget rows: workspace scope uses two workspaces in one month; system scope has a
    # single row per month, so it uses two months.
    clock_a = env.clock(month=6)
    clock_b = env.clock(month=7) if scope == "system" else env.clock(month=6)
    workspace_a = await _workspace_for(env, scope)
    workspace_b = await _workspace_for(env, scope)
    coordinator_a = env.coordinator(clock_a, LIMIT)
    coordinator_b = env.coordinator(clock_b, LIMIT)
    row_a = await env.reserve(coordinator_a, workspace_a, clock_a, LIMIT)
    row_b = await env.reserve(coordinator_b, workspace_b, clock_b, LIMIT)

    # Path A: the reserve-failure path. Path B: refuse_for_call.
    request_id = await env.sync_request(workspace_a, clock_a)
    with pytest.raises(AiBudgetExceeded):
        await coordinator_a.reserve_for_call(
            scope, workspace_a, 1, env.reservation_params(request_id, workspace_a)
        )
    await coordinator_b.refuse_for_call(scope, workspace_b, _task(scope))

    (event_a,), (event_b,) = await env.events(row_a), await env.events(row_b)
    (audit_a,), (audit_b,) = await env.audits(row_a), await env.audits(row_b)

    assert (event_a.event_type, event_a.event_version, event_a.aggregate_type) == (
        event_b.event_type,
        event_b.event_version,
        event_b.aggregate_type,
    )
    assert set(event_a.payload) == set(event_b.payload) == EVENT_KEYS
    same = EVENT_KEYS - {"period_start"} if scope == "system" else EVENT_KEYS
    assert {key: event_a.payload[key] for key in same} == {
        key: event_b.payload[key] for key in same
    }
    assert (audit_a.action, audit_a.actor_type, audit_a.resource_type) == (
        audit_b.action,
        audit_b.actor_type,
        audit_b.resource_type,
    )
    assert set(audit_a.details) == set(audit_b.details) == AUDIT_KEYS
    ignored = {"budget_row_id"} | ({"period_start"} if scope == "system" else set())
    assert {k: v for k, v in audit_a.details.items() if k not in ignored} == {
        k: v for k, v in audit_b.details.items() if k not in ignored
    }
    assert audit_a.event_id == event_a.event_id and audit_b.event_id == event_b.event_id
    # Neither path wrote a usage row beyond the two setup reservations.
    assert await env.usage_count() == 2


async def test_a_refusal_after_the_reserve_failure_path_publishes_nothing_more(
    env: AiDbEnv,
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(coordinator, workspace_id, clock, LIMIT)
    request_id = await env.sync_request(workspace_id, clock)
    with pytest.raises(AiBudgetExceeded):
        await coordinator.reserve_for_call(
            "workspace", workspace_id, 1, env.reservation_params(request_id, workspace_id)
        )
    await coordinator.refuse_for_call("workspace", workspace_id, "GENERATE_HOOK_VARIATIONS")
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1


async def test_workspace_and_system_refusals_are_independent(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    coordinator = env.coordinator(clock, LIMIT)
    workspace_row = await env.reserve(coordinator, workspace_id, clock, LIMIT)
    system_row = await env.reserve(coordinator, None, clock, LIMIT)

    await coordinator.refuse_for_call("workspace", workspace_id, "GENERATE_HOOK_VARIATIONS")
    assert len(await env.events(workspace_row)) == 1
    assert await env.events(system_row) == []
    assert (await env.budget_row(system_row)).exhausted_notified_at is None

    await coordinator.refuse_for_call("system", None, "EMBED_TEXT")
    assert len(await env.events(system_row)) == 1
    assert len(await env.events(workspace_row)) == 1


async def test_a_failing_publish_rolls_the_whole_refusal_back(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    healthy = env.coordinator(clock, LIMIT)
    row_id = await env.reserve(healthy, workspace_id, clock, LIMIT)

    async def failing_publish(*_: Any, **__: Any) -> Any:
        raise RuntimeError("outbox unavailable")

    broken = env.coordinator(clock, LIMIT, publish_event=failing_publish)
    with pytest.raises(RuntimeError):
        await broken.refuse_for_call("workspace", workspace_id, "GENERATE_HOOK_VARIATIONS")

    # Flag, event and audit rolled back together, so a later healthy call still publishes once.
    assert (await env.budget_row(row_id)).exhausted_notified_at is None
    assert await env.events(row_id) == [] and await env.audits(row_id) == []
    await healthy.refuse_for_call("workspace", workspace_id, "GENERATE_HOOK_VARIATIONS")
    assert len(await env.events(row_id)) == 1 and len(await env.audits(row_id)) == 1


async def test_a_lowered_limit_is_stored_by_the_refusal(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    row_id = await env.reserve(env.coordinator(clock, LIMIT), workspace_id, clock, 600)

    await env.coordinator(clock, 500).refuse_for_call(
        "workspace", workspace_id, "GENERATE_HOOK_VARIATIONS"
    )

    snapshot = await env.budget_row(row_id)
    assert snapshot.limit_micro_usd == 500  # the current configured limit, as in the reserve path
    (event,) = await env.events(row_id)
    assert event.payload["limit_micro_usd"] == 500 and event.payload["reserved_micro_usd"] == 600
