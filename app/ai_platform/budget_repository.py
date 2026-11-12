"""Budget repository: SQL statements for budget rows, reservations, refusals, settlement, abandon.

INTERNAL to ai_platform (not exported from the package root). Statements only: no events, no audit
records, no orchestration. The caller owns the transaction.

Rules that hold for every function here:

* The session is passed in. Nothing here commits, rolls back or flushes a transaction boundary.
* Money is a plain ``int`` in micro-USD. ``bool``, non-int and negative values raise ``ValueError``.
* Time is a parameter (INV-22). Nothing here reads a clock.
* Every statement uses bound parameters. Money parameters are cast to ``bigint`` in SQL so an
  expression such as ``80 * :limit`` is never inferred as a 32-bit integer.
* Nothing here takes or logs prompts, completions or user content (INV-2).

Lock order (spec 12.3, INV-32): the ``ai_requests`` row, then the ``ai_usage_records`` row, then the
``ai_budget_periods`` row. The functions in this module only touch the last two, always in that
order: ``settle`` flips the usage record before it updates the budget row, ``abandon_usage_record``
flips the usage record in a CTE that the budget update depends on, and ``reserve`` and
``record_refusal`` touch only the budget row. The caller takes the ``ai_requests`` fence first.

Isolation: the "ensure row, then read its id" pair in ``ensure_budget_row`` and the conditional
updates rely on READ COMMITTED, where a statement that waits on a row lock re-evaluates its WHERE
clause against the committed row. That is what makes the conditions race-free.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import new_uuid7

Scope = Literal["workspace", "system"]
SettleOutcome = Literal["succeeded", "failed"]

_SCOPES = ("workspace", "system")
_OUTCOMES = ("succeeded", "failed")
_CALL_KINDS = ("generation", "repair", "embedding")
_BILLING_MODES = ("free_tier", "paid")
_SNAPSHOT_KEYS = frozenset({"model", "eligible", "reason_code"})
_BIGINT_MAX = 2**63 - 1


class BudgetRepositoryError(RuntimeError):
    """An internal invariant was violated. Messages are fixed text: no values, no content."""


# --------------------------------------------------------------------------------------------
# Validation helpers (all raise ValueError before any statement runs)
# --------------------------------------------------------------------------------------------


def _int(name: str, value: object, *, minimum: int = 0) -> int:
    if type(value) is not int:  # rejects bool and every other non-int type
        raise ValueError(f"{name} must be an int")
    if value < minimum or value > _BIGINT_MAX:
        raise ValueError(f"{name} is out of range")
    return value


def _opt_int(name: str, value: object) -> int | None:
    return None if value is None else _int(name, value)


def _aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"{name} must be a UUID")
    return value


def _opt_str(name: str, value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{name} must be a string or None")
    return value


def _period(value: object) -> date:
    if type(value) is not date or value.day != 1:
        raise ValueError("period_start must be a date on the first day of a month")
    return value


def _scope_pair(scope: object, workspace_id: object) -> None:
    """Same rule as the check constraint ``(scope = 'workspace') = (workspace_id IS NOT NULL)``."""
    if scope not in _SCOPES:
        raise ValueError("scope must be 'workspace' or 'system'")
    if scope == "workspace":
        _uuid("workspace_id", workspace_id)
    elif workspace_id is not None:
        raise ValueError("a system-scope row must not have a workspace_id")


def period_start_for(now: datetime) -> date:
    """First day of the UTC calendar month of a timezone-aware datetime (D-3)."""
    _aware("now", now)
    utc = now.astimezone(UTC)
    return date(utc.year, utc.month, 1)


# --------------------------------------------------------------------------------------------
# Snapshots and parameter objects
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetRowSnapshot:
    """Immutable read of one ``ai_budget_periods`` row."""

    id: UUID
    scope: str
    workspace_id: UUID | None
    period_start: date
    limit_micro_usd: int
    reserved_micro_usd: int
    spent_micro_usd: int
    warning_notified_at: datetime | None
    exhausted_notified_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ReservedUsageRecord:
    """Everything the reservation transaction knows about one call attempt (spec 4.2).

    ``candidate_snapshot`` holds ids and codes only: a list of mappings whose keys are a subset of
    ``model``, ``eligible`` and ``reason_code`` (INV-2).
    """

    request_id: UUID
    attempt_no: int
    scope: str
    workspace_id: UUID | None
    task: str
    call_kind: str
    provider: str
    model: str
    catalog_version: str
    price_version: str
    billing_mode: str
    routing_version: str
    route_rank: int
    candidate_snapshot: Sequence[Mapping[str, str | bool | None]]
    reserved_micro_usd: int
    period_start: date
    started_at: datetime


@dataclass(frozen=True)
class SettleResult:
    flipped: bool
    warning_newly_set: bool


@dataclass(frozen=True)
class ReconciliationMismatch:
    budget_row_id: UUID
    scope: str
    workspace_id: UUID | None
    period_start: date
    spent_micro_usd: int
    ledger_cost_micro_usd: int


# --------------------------------------------------------------------------------------------
# Budget rows
# --------------------------------------------------------------------------------------------

_INSERT_BUDGET = """
INSERT INTO ai_budget_periods
    (id, scope, workspace_id, period_start, limit_micro_usd,
     reserved_micro_usd, spent_micro_usd, created_at, updated_at)
VALUES
    (:id, :scope, :workspace_id, :period_start, CAST(:limit AS bigint), 0, 0, :now, :now)
"""

# The conflict target is index inference: the column list plus the exact WHERE predicate of the
# partial unique index, so Postgres picks uq_ai_budget_periods_workspace_period /
# uq_ai_budget_periods_system_period (spec 4.3).
_ON_CONFLICT_WORKSPACE = (
    " ON CONFLICT (workspace_id, period_start) WHERE scope = 'workspace' DO NOTHING"
)
_ON_CONFLICT_SYSTEM = " ON CONFLICT (period_start) WHERE scope = 'system' DO NOTHING"

_SELECT_WORKSPACE_ROW = """
SELECT id FROM ai_budget_periods
WHERE scope = 'workspace' AND workspace_id = :workspace_id AND period_start = :period_start
"""
_SELECT_SYSTEM_ROW = """
SELECT id FROM ai_budget_periods
WHERE scope = 'system' AND period_start = :period_start
"""


async def ensure_budget_row(
    session: AsyncSession,
    scope: str,
    workspace_id: UUID | None,
    period_start: date,
    limit_micro_usd: int,
    now: datetime,
) -> UUID:
    """Create the budget row for (scope, workspace, period) if absent and return its id.

    ``INSERT ... ON CONFLICT DO NOTHING`` against the partial unique index, then a separate SELECT
    (a concurrent creator's row is visible to the second statement once its commit is done). The
    new row has zero counters and the passed limit; an existing row is left untouched.
    """
    _scope_pair(scope, workspace_id)
    _period(period_start)
    limit = _int("limit_micro_usd", limit_micro_usd)
    _aware("now", now)

    if scope == "workspace":
        conflict, select = _ON_CONFLICT_WORKSPACE, _SELECT_WORKSPACE_ROW
        key: dict[str, Any] = {"workspace_id": workspace_id, "period_start": period_start}
    else:
        conflict, select = _ON_CONFLICT_SYSTEM, _SELECT_SYSTEM_ROW
        key = {"period_start": period_start}

    await session.execute(
        text(_INSERT_BUDGET + conflict),
        {
            "id": new_uuid7(now),
            "scope": scope,
            "workspace_id": workspace_id,
            "period_start": period_start,
            "limit": limit,
            "now": now,
        },
    )
    row_id = (await session.execute(text(select), key)).scalar_one_or_none()
    if row_id is None:
        raise BudgetRepositoryError("budget row missing after ensure")
    assert isinstance(row_id, UUID)
    return row_id


async def get_budget_row(session: AsyncSession, budget_row_id: UUID) -> BudgetRowSnapshot | None:
    """Read one budget row as an immutable snapshot, or None when it does not exist."""
    _uuid("budget_row_id", budget_row_id)
    row = (
        await session.execute(
            text(
                "SELECT id, scope, workspace_id, period_start, limit_micro_usd, "
                "reserved_micro_usd, spent_micro_usd, warning_notified_at, "
                "exhausted_notified_at, created_at, updated_at "
                "FROM ai_budget_periods WHERE id = :id"
            ),
            {"id": budget_row_id},
        )
    ).first()
    if row is None:
        return None
    return BudgetRowSnapshot(
        id=row.id,
        scope=row.scope,
        workspace_id=row.workspace_id,
        period_start=row.period_start,
        limit_micro_usd=row.limit_micro_usd,
        reserved_micro_usd=row.reserved_micro_usd,
        spent_micro_usd=row.spent_micro_usd,
        warning_notified_at=row.warning_notified_at,
        exhausted_notified_at=row.exhausted_notified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --------------------------------------------------------------------------------------------
# Reservation and refusal (touch only the budget row)
# --------------------------------------------------------------------------------------------


async def reserve(
    session: AsyncSession,
    budget_row_id: UUID,
    estimate_micro_usd: int,
    limit_micro_usd: int,
    now: datetime,
) -> bool:
    """Reserve ``estimate`` against the row with ONE conditional UPDATE (spec 12.3 step 2).

    The decision uses the ``limit_micro_usd`` parameter, never the stored column (D-9). The stored
    column is overwritten with the limit seen, for display. Returns True if a row was updated.
    """
    _uuid("budget_row_id", budget_row_id)
    estimate = _int("estimate_micro_usd", estimate_micro_usd)
    limit = _int("limit_micro_usd", limit_micro_usd)
    _aware("now", now)
    result = await session.execute(
        text(
            "UPDATE ai_budget_periods "
            "SET reserved_micro_usd = reserved_micro_usd + CAST(:est AS bigint), "
            "    limit_micro_usd = CAST(:limit AS bigint), updated_at = :now "
            "WHERE id = :id "
            "  AND spent_micro_usd + reserved_micro_usd + CAST(:est AS bigint) "
            "      <= CAST(:limit AS bigint) "
            "RETURNING id"
        ),
        {"id": budget_row_id, "est": estimate, "limit": limit, "now": now},
    )
    return result.first() is not None


async def record_refusal(
    session: AsyncSession,
    budget_row_id: UUID,
    limit_micro_usd: int,
    now: datetime,
) -> bool:
    """Record a refused reservation (spec 12.3 step 4).

    Stores the limit seen, then sets ``exhausted_notified_at`` only if it is still NULL. Returns
    True only if THIS call newly set the flag; the caller publishes the event in a later step.
    The flag is never reset.
    """
    _uuid("budget_row_id", budget_row_id)
    limit = _int("limit_micro_usd", limit_micro_usd)
    _aware("now", now)
    await session.execute(
        text(
            "UPDATE ai_budget_periods SET limit_micro_usd = CAST(:limit AS bigint), "
            "updated_at = :now WHERE id = :id"
        ),
        {"id": budget_row_id, "limit": limit, "now": now},
    )
    result = await session.execute(
        text(
            "UPDATE ai_budget_periods SET exhausted_notified_at = :now "
            "WHERE id = :id AND exhausted_notified_at IS NULL RETURNING id"
        ),
        {"id": budget_row_id, "now": now},
    )
    return result.first() is not None


# --------------------------------------------------------------------------------------------
# Usage records (lock order: the usage record comes before the budget row)
# --------------------------------------------------------------------------------------------

_INSERT_USAGE = """
INSERT INTO ai_usage_records
    (id, request_id, attempt_no, scope, workspace_id, task, call_kind, provider, model,
     catalog_version, price_version, billing_mode, routing_version, route_rank,
     candidate_snapshot, status, reserved_micro_usd, cost_micro_usd, period_start,
     started_at, created_at)
VALUES
    (:id, :request_id, :attempt_no, :scope, :workspace_id, :task, :call_kind, :provider, :model,
     :catalog_version, :price_version, :billing_mode, :routing_version, :route_rank,
     CAST(:candidate_snapshot AS jsonb), 'reserved', CAST(:reserved AS bigint), 0, :period_start,
     :started_at, :started_at)
"""


def _validate_reserved_record(record: ReservedUsageRecord) -> None:
    _uuid("request_id", record.request_id)
    _int("attempt_no", record.attempt_no, minimum=1)
    _scope_pair(record.scope, record.workspace_id)
    for name in (
        "task",
        "provider",
        "model",
        "catalog_version",
        "price_version",
        "routing_version",
    ):
        value = getattr(record, name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
    if record.call_kind not in _CALL_KINDS:
        raise ValueError("call_kind is not allowed")
    if record.billing_mode not in _BILLING_MODES:
        raise ValueError("billing_mode is not allowed")
    _int("route_rank", record.route_rank, minimum=1)
    _int("reserved_micro_usd", record.reserved_micro_usd)
    _aware("started_at", record.started_at)
    if _period(record.period_start) != period_start_for(record.started_at):
        raise ValueError("period_start must be the UTC month of started_at")
    snapshot = record.candidate_snapshot
    if isinstance(snapshot, (str, bytes)) or not isinstance(snapshot, Sequence):
        raise ValueError("candidate_snapshot must be a list of entries")
    for entry in snapshot:
        if not isinstance(entry, Mapping) or not set(entry) <= _SNAPSHOT_KEYS:
            raise ValueError("candidate_snapshot entries allow only model, eligible, reason_code")
        for value in entry.values():
            if value is not None and not isinstance(value, (str, bool)):
                raise ValueError("candidate_snapshot values must be ids and codes only")


async def insert_reserved_usage_record(session: AsyncSession, record: ReservedUsageRecord) -> UUID:
    """Insert the ``reserved`` usage row for a call attempt and return its id (INV-7)."""
    _validate_reserved_record(record)
    record_id = new_uuid7(record.started_at)
    await session.execute(
        text(_INSERT_USAGE),
        {
            "id": record_id,
            "request_id": record.request_id,
            "attempt_no": record.attempt_no,
            "scope": record.scope,
            "workspace_id": record.workspace_id,
            "task": record.task,
            "call_kind": record.call_kind,
            "provider": record.provider,
            "model": record.model,
            "catalog_version": record.catalog_version,
            "price_version": record.price_version,
            "billing_mode": record.billing_mode,
            "routing_version": record.routing_version,
            "route_rank": record.route_rank,
            "candidate_snapshot": json.dumps([dict(entry) for entry in record.candidate_snapshot]),
            "reserved": record.reserved_micro_usd,
            "period_start": record.period_start,
            "started_at": record.started_at,
        },
    )
    return record_id


@dataclass(frozen=True)
class _Settlement:
    """Validated settlement fields (internal)."""

    outcome: str
    input_units: int
    output_units: int
    cost_micro_usd: int
    error_code: str | None
    finish_reason: str | None
    schema_valid: bool | None
    validation_error_count: int | None
    validation_error_types_json: str | None
    latency_ms: int | None


def _validate_settlement(
    outcome: str,
    input_units: int,
    output_units: int,
    cost_micro_usd: int,
    error_code: str | None,
    finish_reason: str | None,
    schema_valid: bool | None,
    validation_error_count: int | None,
    validation_error_types: Sequence[str] | None,
    latency_ms: int | None,
) -> _Settlement:
    if outcome not in _OUTCOMES:
        raise ValueError("outcome must be 'succeeded' or 'failed'")
    if schema_valid is not None and type(schema_valid) is not bool:
        raise ValueError("schema_valid must be a bool or None")
    types_json: str | None = None
    if validation_error_types is not None:
        if isinstance(validation_error_types, (str, bytes)) or not all(
            isinstance(item, str) for item in validation_error_types
        ):
            raise ValueError("validation_error_types must be a list of type names")
        types_json = json.dumps(list(validation_error_types))
    return _Settlement(
        outcome=outcome,
        input_units=_int("input_units", input_units),
        output_units=_int("output_units", output_units),
        cost_micro_usd=_int("cost_micro_usd", cost_micro_usd),
        error_code=_opt_str("error_code", error_code),
        finish_reason=_opt_str("finish_reason", finish_reason),
        schema_valid=schema_valid,
        validation_error_count=_opt_int("validation_error_count", validation_error_count),
        validation_error_types_json=types_json,
        latency_ms=_opt_int("latency_ms", latency_ms),
    )


async def _flip_to_settled(
    session: AsyncSession, record_id: UUID, s: _Settlement, now: datetime
) -> int | None:
    """Flip ``reserved`` to its terminal status. Returns the record's reserved amount, or None."""
    result = await session.execute(
        text(
            "UPDATE ai_usage_records SET status = :outcome, "
            "input_units = CAST(:input_units AS bigint), "
            "output_units = CAST(:output_units AS bigint), "
            "cost_micro_usd = CAST(:cost AS bigint), error_code = :error_code, "
            "finish_reason = :finish_reason, schema_valid = :schema_valid, "
            "validation_error_count = :validation_error_count, "
            "validation_error_types = CAST(:validation_error_types AS jsonb), "
            "latency_ms = :latency_ms, finished_at = :now "
            "WHERE id = :id AND status = 'reserved' RETURNING reserved_micro_usd"
        ),
        {
            "id": record_id,
            "outcome": s.outcome,
            "input_units": s.input_units,
            "output_units": s.output_units,
            "cost": s.cost_micro_usd,
            "error_code": s.error_code,
            "finish_reason": s.finish_reason,
            "schema_valid": s.schema_valid,
            "validation_error_count": s.validation_error_count,
            "validation_error_types": s.validation_error_types_json,
            "latency_ms": s.latency_ms,
            "now": now,
        },
    )
    row = result.first()
    return None if row is None else int(row.reserved_micro_usd)


async def settle_usage_record(
    session: AsyncSession,
    record_id: UUID,
    outcome: str,
    input_units: int,
    output_units: int,
    cost_micro_usd: int,
    error_code: str | None,
    finish_reason: str | None,
    schema_valid: bool | None,
    validation_error_count: int | None,
    validation_error_types: Sequence[str] | None,
    latency_ms: int | None,
    now: datetime,
) -> bool:
    """Flip a ``reserved`` record to ``succeeded`` or ``failed`` (WHERE status = 'reserved').

    True only if THIS call flipped it, so settlement and release happen at most once (INV-7).
    ``cost_micro_usd`` is the metered integer cost. ``validation_error_types`` holds Pydantic error
    type names only.
    """
    _uuid("record_id", record_id)
    _aware("now", now)
    settlement = _validate_settlement(
        outcome,
        input_units,
        output_units,
        cost_micro_usd,
        error_code,
        finish_reason,
        schema_valid,
        validation_error_count,
        validation_error_types,
        latency_ms,
    )
    return await _flip_to_settled(session, record_id, settlement, now) is not None


async def abandon_usage_record(session: AsyncSession, record_id: UUID, now: datetime) -> bool:
    """Abandon a ``reserved`` record in ONE statement (spec 8.2, INV-14).

    A data-modifying CTE flips ``reserved`` to ``abandoned`` (``cost = reserved``, ``finished_at``)
    and, in the same statement, adds that amount to the budget row's ``spent`` and releases the same
    amount from its ``reserved``. The budget row is found through the record's (scope, workspace_id,
    period_start), which the unique indexes make unique. The budget update reads the flipped row, so
    the usage row is locked before the budget row (INV-32). A record that is no longer ``reserved``
    changes nothing. Stale-age selection is the reaper job's concern, not this function's.

    Returns True only if this call abandoned the record. If the record flips but no budget row is
    found, nothing is lost silently: ``BudgetRepositoryError`` is raised so the caller's transaction
    rolls back as a whole.
    """
    _uuid("record_id", record_id)
    _aware("now", now)
    row = (
        await session.execute(
            text(
                """
WITH flipped AS (
    UPDATE ai_usage_records
       SET status = 'abandoned', cost_micro_usd = reserved_micro_usd, finished_at = :now
     WHERE id = :id AND status = 'reserved'
    RETURNING scope, workspace_id, period_start, reserved_micro_usd
), charged AS (
    UPDATE ai_budget_periods AS b
       SET spent_micro_usd = b.spent_micro_usd + f.reserved_micro_usd,
           reserved_micro_usd = b.reserved_micro_usd - f.reserved_micro_usd,
           updated_at = :now
      FROM flipped AS f
     WHERE b.scope = f.scope
       AND b.period_start = f.period_start
       AND b.workspace_id IS NOT DISTINCT FROM f.workspace_id
    RETURNING b.id
)
SELECT (SELECT count(*) FROM flipped) AS flipped, (SELECT count(*) FROM charged) AS charged
"""
            ),
            {"id": record_id, "now": now},
        )
    ).one()
    flipped, charged = int(row.flipped), int(row.charged)
    if flipped and charged != 1:
        raise BudgetRepositoryError("abandoned record has no unique budget row")
    return bool(flipped)


# --------------------------------------------------------------------------------------------
# Settlement of the budget row
# --------------------------------------------------------------------------------------------


async def settle_budget(
    session: AsyncSession,
    budget_row_id: UUID,
    reserved_estimate_micro_usd: int,
    actual_cost_micro_usd: int,
    limit_micro_usd: int,
    now: datetime,
) -> bool:
    """Release the reservation, add the actual cost, then evaluate the 80 % warning.

    ``reserved -= est`` is guarded by ``reserved >= est`` in the same statement. If the guard fails
    (or the row is missing) ``BudgetRepositoryError`` is raised instead of clamping, so the
    ``nonneg`` check constraint never fires in normal use. The warning is evaluated on settled
    ``spent`` only, against the ``limit`` passed with this settlement (F-2), never on
    ``spent + reserved``. Returns True only if THIS call newly set ``warning_notified_at``.
    """
    _uuid("budget_row_id", budget_row_id)
    estimate = _int("reserved_estimate_micro_usd", reserved_estimate_micro_usd)
    actual = _int("actual_cost_micro_usd", actual_cost_micro_usd)
    limit = _int("limit_micro_usd", limit_micro_usd)
    _aware("now", now)

    released = await session.execute(
        text(
            "UPDATE ai_budget_periods "
            "SET reserved_micro_usd = reserved_micro_usd - CAST(:est AS bigint), "
            "    spent_micro_usd = spent_micro_usd + CAST(:actual AS bigint), "
            "    limit_micro_usd = CAST(:limit AS bigint), updated_at = :now "
            "WHERE id = :id AND reserved_micro_usd >= CAST(:est AS bigint) "
            "RETURNING id"
        ),
        {"id": budget_row_id, "est": estimate, "actual": actual, "limit": limit, "now": now},
    )
    if released.first() is None:
        raise BudgetRepositoryError("settlement would release more than is reserved")

    warned = await session.execute(
        text(
            "UPDATE ai_budget_periods SET warning_notified_at = :now "
            "WHERE id = :id AND warning_notified_at IS NULL "
            "  AND spent_micro_usd * 100 >= 80 * CAST(:limit AS bigint) "
            "RETURNING id"
        ),
        {"id": budget_row_id, "limit": limit, "now": now},
    )
    return warned.first() is not None


async def settle(
    session: AsyncSession,
    record_id: UUID,
    outcome: str,
    input_units: int,
    output_units: int,
    cost_micro_usd: int,
    error_code: str | None,
    finish_reason: str | None,
    schema_valid: bool | None,
    validation_error_count: int | None,
    validation_error_types: Sequence[str] | None,
    latency_ms: int | None,
    budget_row_id: UUID,
    reserved_estimate_micro_usd: int,
    limit_micro_usd: int,
    now: datetime,
) -> SettleResult:
    """Settle a call: the usage record first, then, only if it flipped, the budget row.

    Lock order inside: usage record, then budget row (INV-32). The budget is touched only when this
    call flipped the record, so the reservation is released at most once (INV-7). The estimate the
    caller passes must equal the amount stored on the record, otherwise ``BudgetRepositoryError``
    is raised (the caller's transaction rolls back) rather than corrupting the counters.
    """
    _uuid("record_id", record_id)
    _uuid("budget_row_id", budget_row_id)
    estimate = _int("reserved_estimate_micro_usd", reserved_estimate_micro_usd)
    _int("limit_micro_usd", limit_micro_usd)
    _aware("now", now)
    settlement = _validate_settlement(
        outcome,
        input_units,
        output_units,
        cost_micro_usd,
        error_code,
        finish_reason,
        schema_valid,
        validation_error_count,
        validation_error_types,
        latency_ms,
    )

    stored = await _flip_to_settled(session, record_id, settlement, now)
    if stored is None:
        return SettleResult(flipped=False, warning_newly_set=False)
    if stored != estimate:
        raise BudgetRepositoryError("reserved estimate differs from the usage record")
    warning = await settle_budget(
        session, budget_row_id, estimate, cost_micro_usd, limit_micro_usd, now
    )
    return SettleResult(flipped=True, warning_newly_set=warning)


# --------------------------------------------------------------------------------------------
# Reconciliation (read only, never repairs)
# --------------------------------------------------------------------------------------------


async def reconciliation_query(
    session: AsyncSession,
    budget_row_ids: Sequence[UUID] | None = None,
) -> list[ReconciliationMismatch]:
    """Budget rows with ``reserved = 0`` whose ``spent`` differs from their usage-record costs.

    INV-13. Reads only. ``budget_row_ids`` optionally limits the check to those rows (tests share a
    database and must not judge rows they did not create).
    """
    ids: list[UUID] | None = None
    if budget_row_ids is not None:
        ids = [_uuid("budget_row_ids item", item) for item in budget_row_ids]
    rows = (
        await session.execute(
            text(
                """
SELECT id, scope, workspace_id, period_start, spent_micro_usd, ledger FROM (
    SELECT b.id, b.scope, b.workspace_id, b.period_start, b.spent_micro_usd,
           COALESCE((
               SELECT CAST(SUM(u.cost_micro_usd) AS bigint) FROM ai_usage_records AS u
                WHERE u.scope = b.scope
                  AND u.workspace_id IS NOT DISTINCT FROM b.workspace_id
                  AND u.period_start = b.period_start
           ), 0) AS ledger
      FROM ai_budget_periods AS b
     WHERE b.reserved_micro_usd = 0
       AND (CAST(:ids AS uuid[]) IS NULL OR b.id = ANY(CAST(:ids AS uuid[])))
) AS checked
WHERE spent_micro_usd <> ledger
ORDER BY period_start, id
"""
            ),
            {"ids": ids},
        )
    ).all()
    return [
        ReconciliationMismatch(
            budget_row_id=row.id,
            scope=row.scope,
            workspace_id=row.workspace_id,
            period_start=row.period_start,
            spent_micro_usd=int(row.spent_micro_usd),
            ledger_cost_micro_usd=int(row.ledger),
        )
        for row in rows
    ]
