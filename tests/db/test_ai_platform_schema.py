from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User
from app.core import Settings, SystemClock, UUID7Factory
from app.db_migrations.engine import build_async_engine
from app.workspace.models import Workspace

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
PERIOD = date(2026, 11, 1)
JSON_COLUMNS = {"input_payload", "output_payload", "candidate_snapshot", "validation_error_types"}


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


async def _insert(session: AsyncSession, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(
        f"CAST(:{key} AS jsonb)" if key in JSON_COLUMNS else f":{key}" for key in row
    )
    params = {
        k: json.dumps(v) if k in JSON_COLUMNS and v is not None else v for k, v in row.items()
    }
    await session.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"), params)


async def _violation(session: AsyncSession, constraint: str, table: str, row: dict[str, Any]):
    with pytest.raises(IntegrityError) as raised:
        async with session.begin_nested():
            await _insert(session, table, row)
    assert f'"{constraint}"' in str(raised.value)


async def _make_workspace(session: AsyncSession, label: str) -> UUID:
    workspace = Workspace(name=label, slug=f"{label}-{_new_id()}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _make_user(session: AsyncSession) -> UUID:
    user = User(
        email=f"{_new_id()}@example.test",
        password_hash="$argon2id$test-only",
        display_name="ai-test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


def sync_request(workspace_id: UUID | None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _new_id(),
        "scope": "workspace",
        "workspace_id": workspace_id,
        "actor_type": "user",
        "task": "GENERATE_HOOK_VARIATIONS",
        "output_schema_name": "HookVariationSet",
        "output_schema_version": 1,
        "mode": "sync",
        "status": "running",
        "correlation_request_id": "req-test",
        "started_at": NOW,
    }
    row.update(overrides)
    return row


def async_request(workspace_id: UUID | None, **overrides: Any) -> dict[str, Any]:
    row = sync_request(
        workspace_id,
        mode="async",
        status="queued",
        idempotency_key=_new_id(),
        request_fingerprint="a" * 64,
        input_payload={"k": "v"},
        queued_at=NOW,
        started_at=None,
    )
    row.update(overrides)
    return row


def system_request(**overrides: Any) -> dict[str, Any]:
    row = async_request(
        None,
        scope="system",
        actor_type="system",
        task="EMBED_TEXT",
        output_schema_name=None,
        output_schema_version=None,
    )
    row.update(overrides)
    return row


def usage_row(request_id: UUID, workspace_id: UUID | None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _new_id(),
        "request_id": request_id,
        "attempt_no": 1,
        "scope": "workspace" if workspace_id is not None else "system",
        "workspace_id": workspace_id,
        "task": "GENERATE_HOOK_VARIATIONS",
        "call_kind": "generation",
        "provider": "fake-provider",
        "model": "fake-model",
        "catalog_version": "c1",
        "price_version": "p1",
        "billing_mode": "free_tier",
        "routing_version": "r1",
        "route_rank": 1,
        "candidate_snapshot": [],
        "status": "reserved",
        "reserved_micro_usd": 100,
        "period_start": PERIOD,
        "started_at": NOW,
    }
    row.update(overrides)
    return row


def budget_row(workspace_id: UUID | None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": _new_id(),
        "scope": "workspace" if workspace_id is not None else "system",
        "workspace_id": workspace_id,
        "period_start": PERIOD,
        "limit_micro_usd": 25_000_000,
    }
    row.update(overrides)
    return row


async def _count(session: AsyncSession, table: str, **where: Any) -> int:
    clause = " AND ".join(f"{key} = :{key}" for key in where) or "true"
    value = await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {clause}"), where)
    return int(value or 0)


# ---- ai_requests check constraints -------------------------------------------------------


REQUEST_VIOLATIONS: list[tuple[str, str, dict[str, Any]]] = [
    ("ck_ai_requests_scope", "sync", {"scope": "other", "workspace_id": None}),
    ("ck_ai_requests_scope_workspace", "sync", {"workspace_id": None}),
    ("ck_ai_requests_scope_workspace", "sync", {"scope": "system"}),
    ("ck_ai_requests_status", "sync", {"status": "weird"}),
    ("ck_ai_requests_mode", "sync", {"mode": "weird"}),
    ("ck_ai_requests_actor_type", "sync", {"actor_type": "robot"}),
    ("ck_ai_requests_nonneg", "sync", {"input_units": -1}),
    ("ck_ai_requests_nonneg", "sync", {"output_units": -1}),
    ("ck_ai_requests_nonneg", "sync", {"cost_micro_usd": -1}),
    ("ck_ai_requests_nonneg", "sync", {"attempt_count": -1}),
    (
        "ck_ai_requests_nonneg",
        "async",
        {"status": "running", "lease_owner": "w", "lease_expires_at": NOW, "lease_epoch": -1},
    ),
    ("ck_ai_requests_async_key", "async", {"idempotency_key": None}),
    ("ck_ai_requests_async_key", "sync", {"idempotency_key": "KEY"}),
    ("ck_ai_requests_async_fingerprint", "async", {"request_fingerprint": None}),
    ("ck_ai_requests_async_fingerprint", "sync", {"request_fingerprint": "b" * 64}),
    ("ck_ai_requests_schema_name", "sync", {"output_schema_name": None}),
    ("ck_ai_requests_schema_name", "sync", {"output_schema_version": None}),
    ("ck_ai_requests_running_lease", "async", {"status": "running"}),
    (
        "ck_ai_requests_running_lease",
        "async",
        {"status": "running", "lease_owner": "w"},
    ),
    ("ck_ai_requests_sync_no_lease", "sync", {"lease_owner": "w"}),
    ("ck_ai_requests_sync_no_lease", "sync", {"lease_expires_at": NOW}),
    ("ck_ai_requests_sync_no_lease", "sync", {"lease_epoch": 1}),
    ("ck_ai_requests_terminal_completed", "sync", {"status": "succeeded"}),
    ("ck_ai_requests_terminal_completed", "sync", {"status": "failed"}),
    (
        "ck_ai_requests_purged",
        "async",
        {"content_purged_at": NOW, "input_payload": {"k": "v"}},
    ),
    (
        "ck_ai_requests_purged",
        "async",
        {"content_purged_at": NOW, "input_payload": None, "output_payload": {"o": 1}},
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("constraint", "kind", "overrides"), REQUEST_VIOLATIONS)
async def test_ai_requests_check_constraints_reject_bad_rows(
    db_session: AsyncSession, constraint: str, kind: str, overrides: dict[str, Any]
) -> None:
    workspace_id = await _make_workspace(db_session, "req-bad")
    overrides = dict(overrides)
    if overrides.get("idempotency_key") == "KEY":
        overrides["idempotency_key"] = _new_id()
    build = async_request if kind == "async" else sync_request
    target = overrides.pop("workspace_id", workspace_id)
    await _violation(db_session, constraint, "ai_requests", build(target, **overrides))


@pytest.mark.asyncio
async def test_ai_requests_accept_the_valid_shapes(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "req-ok")
    rows = [
        sync_request(workspace_id),  # sync running, no lease
        sync_request(workspace_id, status="succeeded", completed_at=NOW),
        async_request(workspace_id),
        async_request(
            workspace_id, status="running", lease_owner="w", lease_expires_at=NOW, lease_epoch=1
        ),
        async_request(
            workspace_id,
            status="succeeded",
            completed_at=NOW,
            content_purged_at=NOW,
            input_payload=None,
            output_payload=None,
        ),
        system_request(),  # EMBED_TEXT may have no schema
        sync_request(
            workspace_id, task="EMBED_TEXT", output_schema_name=None, output_schema_version=None
        ),
    ]
    for row in rows:
        await _insert(db_session, "ai_requests", row)
    assert await _count(db_session, "ai_requests", workspace_id=workspace_id) == 6


# ---- ai_usage_records / ai_budget_periods check constraints ------------------------------


USAGE_VIOLATIONS: list[tuple[str, dict[str, Any]]] = [
    ("ck_ai_usage_records_scope", {"scope": "bogus", "workspace_id": None}),
    ("ck_ai_usage_records_scope_workspace", {"scope": "workspace", "workspace_id": None}),
    ("ck_ai_usage_records_scope_workspace", {"scope": "system"}),
    ("ck_ai_usage_records_status", {"status": "weird", "finished_at": NOW}),
    ("ck_ai_usage_records_call_kind", {"call_kind": "weird"}),
    ("ck_ai_usage_records_billing_mode", {"billing_mode": "trial"}),
    ("ck_ai_usage_records_nonneg", {"reserved_micro_usd": -1}),
    ("ck_ai_usage_records_nonneg", {"cost_micro_usd": -1}),
    ("ck_ai_usage_records_nonneg", {"input_units": -1}),
    ("ck_ai_usage_records_nonneg", {"output_units": -1}),
    ("ck_ai_usage_records_settled", {"status": "succeeded"}),
    ("ck_ai_usage_records_settled", {"status": "abandoned"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("constraint", "overrides"), USAGE_VIOLATIONS)
async def test_ai_usage_records_check_constraints_reject_bad_rows(
    db_session: AsyncSession, constraint: str, overrides: dict[str, Any]
) -> None:
    workspace_id = await _make_workspace(db_session, "use-bad")
    request = sync_request(workspace_id)
    await _insert(db_session, "ai_requests", request)
    overrides = dict(overrides)
    target = overrides.pop("workspace_id", workspace_id)
    row = usage_row(request["id"], target, **overrides)
    await _violation(db_session, constraint, "ai_usage_records", row)


@pytest.mark.asyncio
async def test_ai_usage_records_accept_valid_shapes(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "use-ok")
    request = sync_request(workspace_id)
    await _insert(db_session, "ai_requests", request)
    await _insert(db_session, "ai_usage_records", usage_row(request["id"], workspace_id))
    await _insert(
        db_session,
        "ai_usage_records",
        usage_row(
            request["id"],
            workspace_id,
            attempt_no=2,
            status="succeeded",
            finished_at=NOW,
            input_units=10,
            output_units=5,
            cost_micro_usd=7,
            schema_valid=True,
            validation_error_types=["missing"],
        ),
    )
    system = system_request()
    await _insert(db_session, "ai_requests", system)
    await _insert(db_session, "ai_usage_records", usage_row(system["id"], None))
    assert await _count(db_session, "ai_usage_records") >= 3


BUDGET_VIOLATIONS: list[tuple[str, dict[str, Any], bool]] = [
    ("ck_ai_budget_periods_scope", {"scope": "bogus"}, False),
    ("ck_ai_budget_periods_scope_workspace", {"scope": "workspace"}, False),
    ("ck_ai_budget_periods_scope_workspace", {"scope": "system"}, True),
    ("ck_ai_budget_periods_nonneg", {"limit_micro_usd": -1}, True),
    ("ck_ai_budget_periods_nonneg", {"reserved_micro_usd": -1}, True),
    ("ck_ai_budget_periods_nonneg", {"spent_micro_usd": -1}, True),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("constraint", "overrides", "with_workspace"), BUDGET_VIOLATIONS)
async def test_ai_budget_periods_check_constraints_reject_bad_rows(
    db_session: AsyncSession, constraint: str, overrides: dict[str, Any], with_workspace: bool
) -> None:
    workspace_id = await _make_workspace(db_session, "bud-bad")
    row = budget_row(workspace_id if with_workspace else None, **overrides)
    if overrides.get("scope") == "system":
        row["workspace_id"] = workspace_id
    await _violation(db_session, constraint, "ai_budget_periods", row)


# ---- unique and partial unique indexes ---------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_idempotency_is_unique_per_workspace(db_session: AsyncSession) -> None:
    first = await _make_workspace(db_session, "idem-a")
    second = await _make_workspace(db_session, "idem-b")
    key = _new_id()
    await _insert(db_session, "ai_requests", async_request(first, idempotency_key=key))
    await _violation(
        db_session,
        "uq_ai_requests_workspace_idempotency",
        "ai_requests",
        async_request(first, idempotency_key=key),
    )
    await _insert(db_session, "ai_requests", async_request(second, idempotency_key=key))
    for _ in range(3):  # sync requests carry no key and never collide
        await _insert(db_session, "ai_requests", sync_request(first))


@pytest.mark.asyncio
async def test_system_idempotency_is_unique(db_session: AsyncSession) -> None:
    key = _new_id()
    await _insert(db_session, "ai_requests", system_request(idempotency_key=key))
    await _violation(
        db_session,
        "uq_ai_requests_system_idempotency",
        "ai_requests",
        system_request(idempotency_key=key),
    )
    await _insert(db_session, "ai_requests", system_request())
    workspace_id = await _make_workspace(db_session, "idem-sys")
    # The same key in a workspace is independent of the system key space.
    await _insert(db_session, "ai_requests", async_request(workspace_id, idempotency_key=key))


@pytest.mark.asyncio
async def test_usage_attempt_is_unique_per_request(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "attempt")
    request = sync_request(workspace_id)
    other = sync_request(workspace_id)
    await _insert(db_session, "ai_requests", request)
    await _insert(db_session, "ai_requests", other)
    await _insert(db_session, "ai_usage_records", usage_row(request["id"], workspace_id))
    await _violation(
        db_session,
        "uq_ai_usage_records_request_attempt",
        "ai_usage_records",
        usage_row(request["id"], workspace_id),
    )
    await _insert(
        db_session, "ai_usage_records", usage_row(request["id"], workspace_id, attempt_no=2)
    )
    await _insert(db_session, "ai_usage_records", usage_row(other["id"], workspace_id))


@pytest.mark.asyncio
async def test_budget_rows_are_unique_per_period(db_session: AsyncSession) -> None:
    first = await _make_workspace(db_session, "bud-a")
    second = await _make_workspace(db_session, "bud-b")
    await _insert(db_session, "ai_budget_periods", budget_row(first))
    await _violation(
        db_session,
        "uq_ai_budget_periods_workspace_period",
        "ai_budget_periods",
        budget_row(first),
    )
    await _insert(db_session, "ai_budget_periods", budget_row(second))
    await _insert(
        db_session, "ai_budget_periods", budget_row(first, period_start=date(2026, 12, 1))
    )
    # System row: one per period, independent of workspace rows.
    system_period = date(2031, 1, 1)
    await _insert(db_session, "ai_budget_periods", budget_row(None, period_start=system_period))
    await _violation(
        db_session,
        "uq_ai_budget_periods_system_period",
        "ai_budget_periods",
        budget_row(None, period_start=system_period),
    )
    await _insert(
        db_session, "ai_budget_periods", budget_row(None, period_start=date(2031, 2, 1))
    )


# ---- foreign keys ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_delete_cascades_to_all_ai_tables(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "cascade-ws")
    keep_id = await _make_workspace(db_session, "cascade-keep")
    request = sync_request(workspace_id)
    keep = sync_request(keep_id)
    await _insert(db_session, "ai_requests", request)
    await _insert(db_session, "ai_requests", keep)
    await _insert(db_session, "ai_usage_records", usage_row(request["id"], workspace_id))
    await _insert(db_session, "ai_usage_records", usage_row(keep["id"], keep_id))
    await _insert(db_session, "ai_budget_periods", budget_row(workspace_id))
    await _insert(db_session, "ai_budget_periods", budget_row(keep_id))

    await db_session.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": workspace_id})

    for table in ("ai_requests", "ai_usage_records", "ai_budget_periods"):
        assert await _count(db_session, table, workspace_id=workspace_id) == 0
        assert await _count(db_session, table, workspace_id=keep_id) == 1


@pytest.mark.asyncio
async def test_request_delete_cascades_to_usage_records(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "cascade-req")
    request = sync_request(workspace_id)
    other = sync_request(workspace_id)
    await _insert(db_session, "ai_requests", request)
    await _insert(db_session, "ai_requests", other)
    await _insert(db_session, "ai_usage_records", usage_row(request["id"], workspace_id))
    await _insert(db_session, "ai_usage_records", usage_row(other["id"], workspace_id))

    await db_session.execute(text("DELETE FROM ai_requests WHERE id = :id"), {"id": request["id"]})

    assert await _count(db_session, "ai_usage_records", request_id=request["id"]) == 0
    assert await _count(db_session, "ai_usage_records", request_id=other["id"]) == 1


@pytest.mark.asyncio
async def test_user_delete_sets_requested_by_user_null(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "setnull")
    user_id = await _make_user(db_session)
    request = sync_request(workspace_id, requested_by_user_id=user_id)
    await _insert(db_session, "ai_requests", request)

    await db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    remaining = await db_session.scalar(
        text("SELECT requested_by_user_id FROM ai_requests WHERE id = :id"), {"id": request["id"]}
    )
    assert remaining is None
    assert await _count(db_session, "ai_requests", id=request["id"]) == 1


@pytest.mark.asyncio
async def test_foreign_keys_reject_unknown_parents(db_session: AsyncSession) -> None:
    workspace_id = await _make_workspace(db_session, "fk-reject")
    await _violation(
        db_session,
        "fk_ai_requests_workspace_id_workspaces",
        "ai_requests",
        sync_request(_new_id()),
    )
    await _violation(
        db_session,
        "fk_ai_usage_records_request_id_ai_requests",
        "ai_usage_records",
        usage_row(_new_id(), workspace_id),
    )


# ---- catalog of names and shapes ---------------------------------------------------------


EXPECTED_CONSTRAINTS = {
    "ai_requests": {
        "pk_ai_requests",
        "fk_ai_requests_workspace_id_workspaces",
        "fk_ai_requests_requested_by_user_id_users",
        *{
            f"ck_ai_requests_{name}"
            for name in (
                "scope",
                "scope_workspace",
                "status",
                "mode",
                "actor_type",
                "nonneg",
                "async_key",
                "async_fingerprint",
                "schema_name",
                "running_lease",
                "sync_no_lease",
                "terminal_completed",
                "purged",
            )
        },
    },
    "ai_usage_records": {
        "pk_ai_usage_records",
        "uq_ai_usage_records_request_attempt",
        "fk_ai_usage_records_request_id_ai_requests",
        "fk_ai_usage_records_workspace_id_workspaces",
        *{
            f"ck_ai_usage_records_{name}"
            for name in (
                "scope",
                "scope_workspace",
                "status",
                "call_kind",
                "billing_mode",
                "nonneg",
                "settled",
            )
        },
    },
    "ai_budget_periods": {
        "pk_ai_budget_periods",
        "fk_ai_budget_periods_workspace_id_workspaces",
        "ck_ai_budget_periods_scope",
        "ck_ai_budget_periods_scope_workspace",
        "ck_ai_budget_periods_nonneg",
    },
}

# name -> (table, unique, partial)
EXPECTED_INDEXES = {
    "uq_ai_requests_workspace_idempotency": ("ai_requests", True, True),
    "uq_ai_requests_system_idempotency": ("ai_requests", True, True),
    "ix_ai_requests_workspace_id_id": ("ai_requests", False, False),
    "ix_ai_requests_running_lease": ("ai_requests", False, True),
    "ix_ai_requests_sync_running": ("ai_requests", False, True),
    "ix_ai_requests_queued_at": ("ai_requests", False, True),
    "ix_ai_requests_purge_candidates": ("ai_requests", False, True),
    "ix_ai_usage_records_workspace_started": ("ai_usage_records", False, False),
    "ix_ai_usage_records_scope_started": ("ai_usage_records", False, True),
    "ix_ai_usage_records_reserved": ("ai_usage_records", False, True),
    "uq_ai_budget_periods_workspace_period": ("ai_budget_periods", True, True),
    "uq_ai_budget_periods_system_period": ("ai_budget_periods", True, True),
}


@pytest.mark.asyncio
async def test_constraint_and_index_names_match_the_spec(db_session: AsyncSession) -> None:
    for table, expected in EXPECTED_CONSTRAINTS.items():
        names = set(
            await db_session.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = CAST(:table AS regclass)"
                ),
                {"table": table},
            )
        )
        assert names == expected, table

    rows = (
        await db_session.execute(
            text(
                "SELECT i.relname, t.relname, x.indisunique, x.indpred IS NOT NULL "
                "FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid "
                "JOIN pg_class t ON t.oid = x.indrelid "
                "WHERE t.relname IN ('ai_requests','ai_usage_records','ai_budget_periods') "
                "AND NOT x.indisprimary AND i.relname NOT LIKE 'uq\\_ai\\_usage\\_records%'"
            )
        )
    ).all()
    actual = {name: (table, unique, partial) for name, table, unique, partial in rows}
    assert actual == EXPECTED_INDEXES


@pytest.mark.asyncio
async def test_partial_index_predicates_are_exact(db_session: AsyncSession) -> None:
    definitions = dict(
        (
            await db_session.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename IN ('ai_requests','ai_usage_records','ai_budget_periods')"
                )
            )
        ).all()
    )
    expected = {
        "uq_ai_requests_workspace_idempotency": [
            "idempotency_key IS NOT NULL",
            "workspace_id IS NOT NULL",
        ],
        "uq_ai_requests_system_idempotency": [
            "scope = 'system'::text",
            "idempotency_key IS NOT NULL",
        ],
        "ix_ai_requests_running_lease": ["status = 'running'::text", "mode = 'async'::text"],
        "ix_ai_requests_sync_running": ["status = 'running'::text", "mode = 'sync'::text"],
        "ix_ai_requests_queued_at": ["status = 'queued'::text"],
        "ix_ai_requests_purge_candidates": [
            "content_purged_at IS NULL",
            "status = ANY (ARRAY['succeeded'::text, 'failed'::text])",
            "input_payload IS NOT NULL",
            "output_payload IS NOT NULL",
        ],
        "ix_ai_usage_records_scope_started": ["scope = 'system'::text"],
        "ix_ai_usage_records_reserved": ["status = 'reserved'::text"],
        "uq_ai_budget_periods_workspace_period": ["scope = 'workspace'::text"],
        "uq_ai_budget_periods_system_period": ["scope = 'system'::text"],
    }
    for name, fragments in expected.items():
        for fragment in fragments:
            assert fragment in definitions[name], (name, fragment)


# ---- migration reversibility (local throwaway database only) -----------------------------


def _public_tables(settings: Settings) -> set[str]:
    async def query() -> set[str]:
        engine = build_async_engine(settings.require_database_url(direct=True), pooled=False)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
                )
                return {name for (name,) in rows}
        finally:
            await engine.dispose()

    return asyncio.run(query())


def test_migration_is_reversible_on_the_local_throwaway_database(
    migrated_test_schema: Settings,
) -> None:
    if migrated_test_schema.test_db_mode != "local":
        pytest.skip("Downgrade runs only on the local throwaway database (TEST_DB_MODE=local)")
    config = Config("alembic.ini")
    ai_tables = {"ai_requests", "ai_usage_records", "ai_budget_periods"}
    earlier = {"users", "workspaces", "content_profiles", "audit_log", "outbox_events"}

    assert ai_tables <= _public_tables(migrated_test_schema)
    try:
        command.downgrade(config, "0007_profile")
        after_downgrade = _public_tables(migrated_test_schema)
        assert not ai_tables & after_downgrade
        assert earlier <= after_downgrade
    finally:
        command.upgrade(config, "head")
    after_upgrade = _public_tables(migrated_test_schema)
    assert ai_tables <= after_upgrade
    assert earlier <= after_upgrade
    command.check(config)  # no drift between models and the migrated schema
