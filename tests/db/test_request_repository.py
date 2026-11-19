"""Database tests for the sync request repository (ai_platform step 5b-1).

Covers spec 4.1 (constraints), 4.5 (sync request lifecycle) and 12.1 (request totals are the sums
over settled usage rows). The repository never commits, so every test commits through its own
session and reads back through another one. Isolation and teardown rules are in
``tests/helpers/ai_request_db_env.py`` (private calendar year, delete by id only, no truncation).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.ai_platform import request_repository as requests_repo
from app.ai_platform.errors import AiErrorCode
from app.core import FakeClock, Settings
from tests.helpers.ai_request_db_env import AiDbEnv, build_env

pytestmark = pytest.mark.db

TIMEOUT_SECONDS = 60


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


async def _insert(
    env: AiDbEnv, clock: FakeClock, workspace_id: UUID | None, *, commit: bool = True
) -> UUID:
    """Insert through the repository in a session that the caller (this helper) commits."""
    system = workspace_id is None
    async with env.sessions() as session:
        await session.begin()
        request_id = await requests_repo.insert_sync_request(
            session,
            scope="system" if system else "workspace",
            workspace_id=workspace_id,
            requested_by_user_id=None,
            actor_type="system" if system else "user",
            task="EMBED_TEXT" if system else "GENERATE_HOOK_VARIATIONS",
            output_schema_name=None if system else "HookVariationSet",
            output_schema_version=None if system else 1,
            correlation_request_id="req-test",
            now=clock.now(),
        )
        env.requests.append(request_id)
        if commit:
            await session.commit()
        else:
            await session.rollback()
    return request_id


async def _complete(env: AiDbEnv, request_id: UUID, **arguments: Any) -> bool:
    async with env.sessions() as session, session.begin():
        return await requests_repo.complete_request(session, request_id, **arguments)


# --------------------------------------------------------------------------------------------
# insert_sync_request
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["workspace", "system"])
async def test_insert_creates_a_running_sync_row_without_lease_key_or_content(
    env: AiDbEnv, scope: str
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace() if scope == "workspace" else None
    request_id = await _insert(env, clock, workspace_id)

    row = await env.request_row(request_id)
    assert row.scope == scope and row.workspace_id == workspace_id
    assert row.mode == "sync" and row.status == "running"
    assert row.task == ("EMBED_TEXT" if workspace_id is None else "GENERATE_HOOK_VARIATIONS")
    assert (row.output_schema_name is None) == (workspace_id is None)
    assert (row.output_schema_version is None) == (workspace_id is None)
    assert row.started_at == clock.now()
    assert row.queued_at is None and row.completed_at is None
    assert row.idempotency_key is None and row.request_fingerprint is None
    assert row.input_payload is None and row.output_payload is None
    assert row.lease_owner is None and row.lease_expires_at is None and row.heartbeat_at is None
    assert row.lease_epoch == 0 and row.attempt_count == 0
    assert row.error_code is None and row.routing_version is None
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (0, 0, 0)
    assert row.correlation_request_id == "req-test"
    assert row.requested_by_user_id is None and row.content_purged_at is None


async def test_the_row_is_visible_to_another_session_only_after_the_caller_commits(
    env: AiDbEnv,
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    async with env.sessions() as writer:
        await writer.begin()
        request_id = await requests_repo.insert_sync_request(
            writer,
            scope="workspace",
            workspace_id=workspace_id,
            requested_by_user_id=None,
            actor_type="user",
            task="GENERATE_HOOK_VARIATIONS",
            output_schema_name="HookVariationSet",
            output_schema_version=1,
            correlation_request_id="req-test",
            now=clock.now(),
        )
        env.requests.append(request_id)
        # The repository never commits: another session sees nothing yet.
        assert await env.count_requests([request_id]) == 0
        await writer.commit()
    assert await env.count_requests([request_id]) == 1


async def test_a_caller_rollback_undoes_the_insert(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id, commit=False)
    assert await env.count_requests([request_id]) == 0


async def test_each_insert_gets_its_own_id(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    first = await _insert(env, clock, workspace_id)
    second = await _insert(env, clock, workspace_id)
    assert first != second and await env.count_requests([first, second]) == 2


async def test_a_validation_failure_writes_no_row(env: AiDbEnv) -> None:
    clock = env.clock()
    marker = f"never-{uuid4()}"
    async with env.sessions() as session, session.begin():
        with pytest.raises(ValueError):
            await requests_repo.insert_sync_request(
                session,
                scope="workspace",
                workspace_id=None,
                requested_by_user_id=None,
                actor_type="user",
                task="GENERATE_HOOK_VARIATIONS",
                output_schema_name="HookVariationSet",
                output_schema_version=1,
                correlation_request_id=marker,
                now=clock.now(),
            )
        count = (
            await session.execute(
                text("SELECT count(*) FROM ai_requests WHERE correlation_request_id = :marker"),
                {"marker": marker},
            )
        ).scalar_one()
    assert count == 0


async def test_an_unknown_workspace_is_rejected_by_the_foreign_key(env: AiDbEnv) -> None:
    clock = env.clock()
    with pytest.raises(IntegrityError) as raised:
        async with env.sessions() as session, session.begin():
            await requests_repo.insert_sync_request(
                session,
                scope="workspace",
                workspace_id=uuid4(),
                requested_by_user_id=None,
                actor_type="user",
                task="GENERATE_HOOK_VARIATIONS",
                output_schema_name="HookVariationSet",
                output_schema_version=1,
                correlation_request_id="req-test",
                now=clock.now(),
            )
    assert "workspace" in str(raised.value).lower()


_SYNC_BASE: dict[str, Any] = {
    "actor_type": "user",
    "task": "GENERATE_HOOK_VARIATIONS",
    "output_schema_name": "HookVariationSet",
    "output_schema_version": 1,
    "mode": "sync",
    "status": "running",
    "correlation_request_id": "req-test",
}


@pytest.mark.parametrize(
    ("constraint", "overrides"),
    [
        ("ck_ai_requests_scope_workspace", {"scope": "workspace", "workspace_id": None}),
        ("ck_ai_requests_scope_workspace", {"scope": "system", "workspace_id": "WORKSPACE"}),
        ("ck_ai_requests_sync_no_lease", {"scope": "system", "lease_owner": "worker-1"}),
        ("ck_ai_requests_sync_no_lease", {"scope": "system", "lease_epoch": 1}),
        ("ck_ai_requests_async_key", {"scope": "system", "idempotency_key": "KEY"}),
        ("ck_ai_requests_async_fingerprint", {"scope": "system", "request_fingerprint": "f" * 64}),
        (
            "ck_ai_requests_schema_name",
            {"scope": "system", "output_schema_name": None, "output_schema_version": None},
        ),
        ("ck_ai_requests_terminal_completed", {"scope": "system", "status": "failed"}),
        ("ck_ai_requests_status", {"scope": "system", "status": "abandoned"}),
    ],
)
async def test_the_database_rejects_impossible_sync_rows(
    env: AiDbEnv, constraint: str, overrides: dict[str, Any]
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    columns: dict[str, Any] = {
        **_SYNC_BASE,
        "started_at": clock.now(),
        "workspace_id": None,
        **overrides,
    }
    if columns["workspace_id"] == "WORKSPACE":
        columns["workspace_id"] = workspace_id
    if columns.get("idempotency_key") == "KEY":
        columns["idempotency_key"] = uuid4()
    with pytest.raises(IntegrityError) as raised:
        await env.raw_request(**columns)
    assert f'"{constraint}"' in str(raised.value)


# --------------------------------------------------------------------------------------------
# complete_request
# --------------------------------------------------------------------------------------------


async def _request_with_usage(env: AiDbEnv, clock: FakeClock) -> tuple[UUID, UUID]:
    """A running sync request with one usage row of every status, as a workspace request."""
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    usage: list[dict[str, Any]] = [
        # succeeded, with cost
        {"status": "succeeded", "input_units": 100, "output_units": 50, "cost_micro_usd": 700,
         "reserved_micro_usd": 900},
        # failed with cost 0 (a provider error without usage)
        {"status": "failed", "input_units": 20, "output_units": 0, "cost_micro_usd": 0,
         "reserved_micro_usd": 400},
        # failed with NULL units: counts as 0
        {"status": "failed", "input_units": None, "output_units": None, "cost_micro_usd": 0,
         "reserved_micro_usd": 400},
        # abandoned: cost equals the reservation, units unknown
        {"status": "abandoned", "input_units": None, "output_units": None, "cost_micro_usd": 300,
         "reserved_micro_usd": 300},
        # reserved: not settled yet, must be excluded even if it carried figures
        {"status": "reserved", "input_units": 5555, "output_units": 4444, "cost_micro_usd": 9999,
         "reserved_micro_usd": 999},
    ]  # fmt: skip
    for number, row in enumerate(usage, start=1):
        await env.add_usage(request_id, number, clock, workspace_id=workspace_id, **row)
    return request_id, workspace_id


async def test_totals_equal_the_sum_over_the_settled_usage_rows(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id, _ = await _request_with_usage(env, clock)
    done = clock.now()

    assert await _complete(
        env, request_id, status="succeeded", error_code=None, routing_version="r1", now=done
    )

    row = await env.request_row(request_id)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (120, 50, 1000)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == await env.independent_sums(
        request_id
    )
    assert row.status == "succeeded" and row.error_code is None
    assert row.completed_at == done and row.updated_at == done
    assert row.routing_version == "r1"


async def test_a_failed_completion_stores_the_error_code_and_the_totals(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id, _ = await _request_with_usage(env, clock)
    assert await _complete(
        env,
        request_id,
        status="failed",
        error_code=AiErrorCode.OUTPUT_INVALID.value,
        now=clock.now(),
    )
    row = await env.request_row(request_id)
    assert row.status == "failed" and row.error_code == "output_invalid"
    assert row.completed_at == clock.now()
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (120, 50, 1000)
    assert row.output_payload is None and row.routing_version is None


async def test_a_request_without_usage_rows_completes_with_zero_totals(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    assert await _complete(
        env,
        request_id,
        status="failed",
        error_code=AiErrorCode.BUDGET_EXCEEDED.value,
        now=clock.now(),
    )
    row = await env.request_row(request_id)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (0, 0, 0)
    assert row.status == "failed" and row.error_code == "budget_exceeded"
    assert row.completed_at == clock.now()
    assert await env.usage_count() == 0


async def test_totals_only_count_this_requests_rows(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    mine = await _insert(env, clock, workspace_id)
    other = await _insert(env, clock, workspace_id)
    await env.add_usage(
        mine, 1, clock, status="succeeded", input_units=1, output_units=2, cost_micro_usd=3,
        reserved_micro_usd=3, workspace_id=workspace_id,
    )  # fmt: skip
    await env.add_usage(
        other, 1, clock, status="succeeded", input_units=10, output_units=20, cost_micro_usd=30,
        reserved_micro_usd=30, workspace_id=workspace_id,
    )  # fmt: skip
    assert await _complete(env, mine, status="succeeded", error_code=None, now=clock.now())
    row = await env.request_row(mine)
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (1, 2, 3)
    assert (await env.request_row(other)).status == "running"


async def test_a_second_completion_returns_false_and_changes_nothing(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id, workspace_id = await _request_with_usage(env, clock)
    first_time = clock.now()
    assert await _complete(env, request_id, status="succeeded", error_code=None, now=first_time)
    before = await env.request_row(request_id)

    # More ledger rows and a different outcome must not matter any more.
    await env.add_usage(
        request_id, 6, clock, status="succeeded", input_units=1, output_units=1,
        cost_micro_usd=1, reserved_micro_usd=1, workspace_id=workspace_id,
    )  # fmt: skip
    later = first_time + timedelta(minutes=5)
    assert not await _complete(
        env,
        request_id,
        status="failed",
        error_code=AiErrorCode.OUTPUT_INVALID.value,
        routing_version="other",
        now=later,
    )
    assert not await _complete(
        env, request_id, status="succeeded", error_code=None, output_payload={"a": 1}, now=later
    )
    assert tuple(await env.request_row(request_id)) == tuple(before)


@pytest.mark.parametrize("state", ["succeeded", "failed"])
async def test_completing_an_already_terminal_row_returns_false(env: AiDbEnv, state: str) -> None:
    clock = env.clock()
    request_id = await env.raw_request(
        **{
            **_SYNC_BASE,
            "scope": "system",
            "workspace_id": None,
            "started_at": clock.now(),
            "status": state,
            "completed_at": clock.now(),
            "error_code": None if state == "succeeded" else "no_route",
        }
    )
    before = await env.request_row(request_id)
    assert not await _complete(
        env, request_id, status="succeeded", error_code=None, now=clock.now()
    )
    assert tuple(await env.request_row(request_id)) == tuple(before)


async def test_completing_a_queued_async_row_returns_false(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id = await env.raw_request(
        scope="system",
        workspace_id=None,
        actor_type="system",
        task="GENERATE_HOOK_VARIATIONS",
        output_schema_name="HookVariationSet",
        output_schema_version=1,
        mode="async",
        status="queued",
        idempotency_key=uuid4(),
        request_fingerprint="a" * 64,
        correlation_request_id="req-test",
        queued_at=clock.now(),
    )
    assert not await _complete(
        env, request_id, status="succeeded", error_code=None, now=clock.now()
    )
    row = await env.request_row(request_id)
    assert row.status == "queued" and row.completed_at is None


async def test_completing_an_unknown_request_returns_false(env: AiDbEnv) -> None:
    assert not await _complete(
        env, uuid4(), status="succeeded", error_code=None, now=env.clock().now()
    )


async def test_output_payload_is_stored_only_for_a_succeeded_request(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    succeeded = await _insert(env, clock, workspace_id)
    failed = await _insert(env, clock, workspace_id)
    payload = {"hooks": ["a", "b"], "n": 2}

    assert await _complete(
        env, succeeded, status="succeeded", error_code=None, output_payload=payload,
        now=clock.now(),
    )  # fmt: skip
    assert (await env.request_row(succeeded)).output_payload == payload

    with pytest.raises(ValueError):
        await _complete(
            env,
            failed,
            status="failed",
            error_code=AiErrorCode.OUTPUT_INVALID.value,
            output_payload=payload,
            now=clock.now(),
        )
    row = await env.request_row(failed)
    assert row.status == "running" and row.output_payload is None

    assert await _complete(
        env, failed, status="failed", error_code=AiErrorCode.OUTPUT_INVALID.value, now=clock.now()
    )
    assert (await env.request_row(failed)).output_payload is None


async def test_a_succeeded_request_without_a_payload_keeps_the_payload_null(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    assert await _complete(env, request_id, status="succeeded", error_code=None, now=clock.now())
    assert (await env.request_row(request_id)).output_payload is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"status": "running", "error_code": None},
        {"status": "queued", "error_code": None},
        {"status": "abandoned", "error_code": "execution_abandoned"},
        {"status": "failed", "error_code": None},
        {"status": "failed", "error_code": "not_a_real_code"},
        {"status": "succeeded", "error_code": "output_invalid"},
    ],
)
async def test_an_invalid_status_or_error_code_raises_and_leaves_the_row_running(
    env: AiDbEnv, arguments: dict[str, Any]
) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    with pytest.raises(ValueError):
        await _complete(env, request_id, now=clock.now(), **arguments)
    row = await env.request_row(request_id)
    assert row.status == "running" and row.error_code is None and row.completed_at is None


async def test_the_routing_version_is_kept_when_none_is_given(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    async with env.sessions() as session, session.begin():
        await session.execute(
            text("UPDATE ai_requests SET routing_version = 'kept' WHERE id = :id"),
            {"id": request_id},
        )
    assert await _complete(env, request_id, status="succeeded", error_code=None, now=clock.now())
    assert (await env.request_row(request_id)).routing_version == "kept"


async def test_concurrent_completions_let_exactly_one_win(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id, _ = await _request_with_usage(env, clock)
    async with asyncio.timeout(TIMEOUT_SECONDS):
        outcomes = await asyncio.gather(
            *(
                _complete(
                    env,
                    request_id,
                    status="succeeded" if number % 2 else "failed",
                    error_code=None if number % 2 else AiErrorCode.OUTPUT_INVALID.value,
                    now=clock.now(),
                )
                for number in range(1, 13)
            )
        )
    assert outcomes.count(True) == 1
    row = await env.request_row(request_id)
    assert row.status in ("succeeded", "failed") and row.completed_at == clock.now()
    assert (row.input_units, row.output_units, row.cost_micro_usd) == (120, 50, 1000)
    assert (row.status == "succeeded") == (row.error_code is None)


async def test_completion_does_not_commit_for_the_caller(env: AiDbEnv) -> None:
    clock = env.clock()
    workspace_id = await env.new_workspace()
    request_id = await _insert(env, clock, workspace_id)
    async with env.sessions() as session:
        await session.begin()
        assert await requests_repo.complete_request(
            session, request_id, status="succeeded", error_code=None, now=clock.now()
        )
        assert (await env.request_row(request_id)).status == "running"  # not committed yet
        await session.rollback()
    assert (await env.request_row(request_id)).status == "running"


# --------------------------------------------------------------------------------------------
# get_request_snapshot
# --------------------------------------------------------------------------------------------


async def test_snapshot_reads_the_metadata_and_is_immutable(env: AiDbEnv) -> None:
    clock = env.clock()
    request_id, workspace_id = await _request_with_usage(env, clock)
    await _complete(env, request_id, status="succeeded", error_code=None, now=clock.now())

    async with env.sessions() as session, session.begin():
        snapshot = await requests_repo.get_request_snapshot(session, request_id)
    assert snapshot is not None
    assert snapshot.id == request_id
    assert snapshot.status == "succeeded" and snapshot.error_code is None
    assert snapshot.scope == "workspace" and snapshot.workspace_id == workspace_id
    assert snapshot.mode == "sync" and snapshot.task == "GENERATE_HOOK_VARIATIONS"
    assert (snapshot.input_units, snapshot.output_units, snapshot.cost_micro_usd) == (120, 50, 1000)
    assert snapshot.completed_at == clock.now() and snapshot.content_purged_at is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.status = "failed"  # type: ignore[misc]


async def test_snapshot_of_a_missing_request_is_none(env: AiDbEnv) -> None:
    async with env.sessions() as session, session.begin():
        assert await requests_repo.get_request_snapshot(session, uuid4()) is None
