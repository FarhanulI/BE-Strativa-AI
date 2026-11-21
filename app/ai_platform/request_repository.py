"""Request repository: SQL for the sync request row of ``ai_requests`` (spec 4.1, 4.5).

INTERNAL to ai_platform (not exported from the package root). Statements only: no events, no audit
records, no orchestration. The caller owns the transaction.

Rules that hold for every function here:

* The session is passed in. Nothing here commits, rolls back or flushes a transaction boundary.
* Counts and money are plain ``int``. ``bool``, non-int and negative values raise ``ValueError``.
* Time is a parameter (INV-22). Nothing here reads a clock.
* Every statement uses bound parameters.
* Nothing here takes or logs prompts, completions or user content. The only payload accepted is the
  already-validated output of a succeeded request, which is stored and never logged.
* Validation raises ``ValueError`` with fixed text, before any statement runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_platform.enums import AiTaskName
from app.ai_platform.errors import AiErrorCode
from app.ai_platform.requests import validate_instructions_version
from app.core import new_uuid7

CompletionStatus = Literal["succeeded", "failed"]

_SCOPES = ("workspace", "system")
_ACTORS = ("user", "system", "worker")
_COMPLETION_STATUSES = ("succeeded", "failed")
_TASKS = frozenset(task.value for task in AiTaskName)
_ERROR_CODES = frozenset(code.value for code in AiErrorCode)
_BIGINT_MAX = 2**63 - 1
_INT_MAX = 2**31 - 1


# --------------------------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------------------------


def _aware(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ValueError(f"{name} must be a UUID")
    return value


def _check_scope(scope: object, workspace_id: object) -> None:
    """Same rule as the check constraint ``(scope = 'workspace') = (workspace_id IS NOT NULL)``."""
    if scope not in _SCOPES:
        raise ValueError("scope must be 'workspace' or 'system'")
    if scope == "workspace":
        _uuid("workspace_id", workspace_id)
    elif workspace_id is not None:
        raise ValueError("a system-scope request must not have a workspace_id")


def _check_schema(task: str, name: object, version: object) -> None:
    """Schema name and version are NULL only for ``EMBED_TEXT`` (``ck_ai_requests_schema_name``)."""
    if task == AiTaskName.EMBED_TEXT.value:
        if name is not None or version is not None:
            raise ValueError("EMBED_TEXT has no output schema")
        return
    if not isinstance(name, str) or not name:
        raise ValueError("output_schema_name must be a non-empty string")
    if type(version) is not int or version < 1 or version > _INT_MAX:
        raise ValueError("output_schema_version must be a positive int")


def _output_json(output_payload: object) -> str:
    if not isinstance(output_payload, dict):
        raise ValueError("output_payload must be a dict")
    try:
        return json.dumps(output_payload, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("output_payload must be JSON-serialisable") from None


# --------------------------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestSnapshot:
    """Immutable read of the metadata of one ``ai_requests`` row. Never carries content."""

    id: UUID
    status: str
    error_code: str | None
    scope: str
    workspace_id: UUID | None
    mode: str
    task: str
    input_units: int
    output_units: int
    cost_micro_usd: int
    completed_at: datetime | None
    content_purged_at: datetime | None


# --------------------------------------------------------------------------------------------
# Statements
# --------------------------------------------------------------------------------------------

_INSERT_SYNC = """
INSERT INTO ai_requests
    (id, scope, workspace_id, requested_by_user_id, actor_type, task, output_schema_name,
     output_schema_version, instructions_version, mode, status, lease_epoch,
     correlation_request_id, started_at, created_at, updated_at)
VALUES
    (:id, :scope, :workspace_id, :requested_by_user_id, :actor_type, :task, :schema_name,
     :schema_version, :instructions_version, 'sync', 'running', 0, :correlation, :now, :now, :now)
"""

# One conditional UPDATE: the status guard makes completion happen at most once. The totals are
# scalar subqueries so a request without any ledger row still completes with zeros. Only settled
# rows count (a ``reserved`` row has no figures yet).
_SUM_OF = (
    "(SELECT CAST(COALESCE(SUM(COALESCE(u.{column}, 0)), 0) AS bigint) FROM ai_usage_records u "
    "WHERE u.request_id = r.id AND u.status IN ('succeeded', 'failed', 'abandoned'))"
)

_COMPLETE = f"""
UPDATE ai_requests r
SET status = :status,
    error_code = :error_code,
    completed_at = :now,
    routing_version = COALESCE(:routing_version, r.routing_version),
    output_payload = COALESCE(CAST(:output_payload AS jsonb), r.output_payload),
    input_units = {_SUM_OF.format(column="input_units")},
    output_units = {_SUM_OF.format(column="output_units")},
    cost_micro_usd = {_SUM_OF.format(column="cost_micro_usd")},
    updated_at = :now
WHERE r.id = :id AND r.status = 'running'
RETURNING r.id
"""

_SELECT_SNAPSHOT = """
SELECT id, status, error_code, scope, workspace_id, mode, task, input_units, output_units,
       cost_micro_usd, completed_at, content_purged_at
FROM ai_requests WHERE id = :id
"""


async def insert_sync_request(
    session: AsyncSession,
    *,
    scope: str,
    workspace_id: UUID | None,
    requested_by_user_id: UUID | None,
    actor_type: str,
    task: str,
    output_schema_name: str | None,
    output_schema_version: int | None,
    correlation_request_id: str,
    now: datetime,
    instructions_version: str | None = None,
) -> UUID:
    """Insert a ``sync`` request row, ``running``, and return its id (spec 4.5).

    ``started_at = now``; ``queued_at``, the idempotency key, the fingerprint, the input payload and
    the lease fields stay NULL and ``lease_epoch`` is 0. Nothing is committed: the caller commits.
    """
    _check_scope(scope, workspace_id)
    if requested_by_user_id is not None:
        _uuid("requested_by_user_id", requested_by_user_id)
    if actor_type not in _ACTORS:
        raise ValueError("actor_type must be 'user', 'system' or 'worker'")
    if task not in _TASKS:
        raise ValueError("task is not a registered task")
    _check_schema(task, output_schema_name, output_schema_version)
    validate_instructions_version(instructions_version)
    if instructions_version is not None and task == AiTaskName.EMBED_TEXT.value:
        raise ValueError("EMBED_TEXT has no instructions_version")
    if not isinstance(correlation_request_id, str) or not correlation_request_id:
        raise ValueError("correlation_request_id must be a non-empty string")
    _aware("now", now)

    request_id = new_uuid7(now)
    await session.execute(
        text(_INSERT_SYNC),
        {
            "id": request_id,
            "scope": scope,
            "workspace_id": workspace_id,
            "requested_by_user_id": requested_by_user_id,
            "actor_type": actor_type,
            "task": task,
            "schema_name": output_schema_name,
            "schema_version": output_schema_version,
            "instructions_version": instructions_version,
            "correlation": correlation_request_id,
            "now": now,
        },
    )
    return request_id


async def complete_request(
    session: AsyncSession,
    request_id: UUID,
    *,
    status: str,
    error_code: str | None,
    output_payload: dict[str, Any] | None = None,
    routing_version: str | None = None,
    now: datetime,
) -> bool:
    """Complete a ``running`` request in ONE conditional UPDATE; True only if this call did it.

    Sets the status, ``error_code``, ``completed_at``, the optional ``routing_version`` and
    ``output_payload``, and the three totals as the sum over the request's settled usage rows
    (``succeeded``, ``failed`` or ``abandoned``; NULL units count as 0). A ``failed`` request needs
    a valid ``AiErrorCode`` value, a ``succeeded`` one must have no ``error_code`` and is the only
    one that may carry an ``output_payload``. A second call, or a call on a row that is not
    ``running``, changes nothing and returns False.
    """
    _uuid("request_id", request_id)
    if status not in _COMPLETION_STATUSES:
        raise ValueError("status must be 'succeeded' or 'failed'")
    if status == "succeeded":
        if error_code is not None:
            raise ValueError("a succeeded request must not have an error_code")
    elif not isinstance(error_code, str) or error_code not in _ERROR_CODES:
        raise ValueError("a failed request needs a valid error_code")
    payload_json: str | None = None
    if output_payload is not None:
        if status != "succeeded":
            raise ValueError("only a succeeded request may carry an output_payload")
        payload_json = _output_json(output_payload)
    if routing_version is not None and (
        not isinstance(routing_version, str) or not routing_version
    ):
        raise ValueError("routing_version must be a non-empty string or None")
    _aware("now", now)

    result = await session.execute(
        text(_COMPLETE),
        {
            "id": request_id,
            "status": status,
            "error_code": error_code,
            "now": now,
            "routing_version": routing_version,
            "output_payload": payload_json,
        },
    )
    return result.first() is not None


async def get_request_snapshot(session: AsyncSession, request_id: UUID) -> RequestSnapshot | None:
    """Read the metadata of one request as an immutable snapshot, or None when it is absent."""
    _uuid("request_id", request_id)
    row = (await session.execute(text(_SELECT_SNAPSHOT), {"id": request_id})).first()
    if row is None:
        return None
    return RequestSnapshot(
        id=row.id,
        status=row.status,
        error_code=row.error_code,
        scope=row.scope,
        workspace_id=row.workspace_id,
        mode=row.mode,
        task=row.task,
        input_units=row.input_units,
        output_units=row.output_units,
        cost_micro_usd=row.cost_micro_usd,
        completed_at=row.completed_at,
        content_purged_at=row.content_purged_at,
    )
