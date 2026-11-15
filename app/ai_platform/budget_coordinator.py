"""BudgetCoordinator: the reservation, refusal and settlement transactions of spec 12.3.

INTERNAL to ai_platform (not exported from the package root). It sits on the 3a budget repository
and adds what the repository deliberately leaves out: it owns the transactions (spec 5.2) and
publishes the two budget events with their audit records in the right transaction.

Rules:

* Every method opens its OWN short transaction from the injected ``async_sessionmaker`` and nothing
  but database work happens inside it. No provider call, no network wait, no sleep (INV-6).
* Time comes from the injected ``Clock`` only (INV-22).
* A refusal commits (flag, event, audit) and only then raises ``AiBudgetExceeded``. It writes no
  usage record and makes no reservation.
* A settlement that newly sets the warning flag publishes ``ai.budget_threshold_reached`` and
  appends the audit record in the SAME transaction. If either fails the whole transaction rolls
  back (settlement and flag included) and the error propagates to the caller.
* Log fields and audit details are ids, codes, scope, period and integer amounts only. No method
  here accepts free text from a caller; the string parameters are ids and codes (spec 12.4).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as repo
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.errors import AiBudgetExceeded
from app.ai_platform.events import AI_BUDGET_AGGREGATE, AiBudgetExhausted, AiBudgetThresholdReached
from app.core import Clock
from app.events_outbox import DomainEvent, OutboxEvent, publish
from app.observability_audit import AuditRecord, append_audit

PublishFn = Callable[[AsyncSession, DomainEvent], Awaitable[OutboxEvent]]

EXHAUSTED_ACTION = "ai.budget.exhausted"
THRESHOLD_ACTION = "ai.budget.threshold_reached"
AUDIT_RESOURCE_TYPE = "ai_budget"
AUDIT_ACTOR_TYPE = "system"



def _log() -> Any:
    """A fresh bound logger per use, so log capture and later logging configuration both apply."""
    return structlog.get_logger("app.ai_platform.budget")


@dataclass(frozen=True)
class ReservationParams:
    """What the reservation transaction records about a call attempt (spec 4.2).

    Ids and codes only. Scope, workspace, reserved amount, period and start time are not here: the
    coordinator takes them from its own arguments and the Clock so they cannot disagree.
    """

    request_id: UUID
    attempt_no: int
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


@dataclass(frozen=True)
class ReservationResult:
    usage_record_id: UUID
    budget_row_id: UUID
    limit_micro_usd: int


@dataclass(frozen=True)
class SettlementOutcome:
    """Outcome fields of one call. ``error_code`` and ``finish_reason`` are codes, never text."""

    outcome: repo.SettleOutcome
    input_units: int
    output_units: int
    cost_micro_usd: int
    error_code: str | None = None
    finish_reason: str | None = None
    schema_valid: bool | None = None
    validation_error_count: int | None = None
    validation_error_types: Sequence[str] | None = None
    latency_ms: int | None = None


def _check_scope(scope: object, workspace_id: object) -> None:
    if scope not in ("workspace", "system"):
        raise ValueError("scope must be 'workspace' or 'system'")
    if scope == "workspace":
        if not isinstance(workspace_id, UUID):
            raise ValueError("workspace_id must be a UUID")
    elif workspace_id is not None:
        raise ValueError("a system-scope call must not have a workspace_id")


def _check_amount(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


class BudgetCoordinator:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        clock: Clock,
        config: AiPlatformConfig,
        publish_event: PublishFn = publish,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._config = config
        self._publish = publish_event

    def limit_for_scope(self, scope: str) -> int:
        """The current configured limit in micro-USD for a scope (D-9)."""
        if scope == "workspace":
            return self._config.workspace_limit_micro_usd
        if scope == "system":
            return self._config.system_limit_micro_usd
        raise ValueError("scope must be 'workspace' or 'system'")

    # ----------------------------------------------------------------------------------------
    # Reservation and refusal
    # ----------------------------------------------------------------------------------------

    async def reserve_for_call(
        self,
        scope: repo.Scope,
        workspace_id: UUID | None,
        estimate_micro_usd: int,
        usage_record_params: ReservationParams,
    ) -> ReservationResult:
        """Reserve ``estimate`` for one call and write its ``reserved`` usage record.

        One transaction (spec 12.3): ensure the row, reserve, insert the record, commit. When the
        reservation is refused, the same transaction records the refusal, publishes
        ``ai.budget_exhausted`` with its audit record on the FIRST refusal only, and commits. Only
        then ``AiBudgetExceeded`` is raised. A refusal writes no usage row and reserves nothing.
        """
        _check_scope(scope, workspace_id)
        estimate = _check_amount("estimate_micro_usd", estimate_micro_usd)
        params = usage_record_params
        limit = self.limit_for_scope(scope)
        now = self._clock.now()
        period = repo.period_start_for(now)

        async with self._sessions() as session, session.begin():
            budget_row_id = await repo.ensure_budget_row(
                session, scope, workspace_id, period, limit, now
            )
            if await repo.reserve(session, budget_row_id, estimate, limit, now):
                record_id = await repo.insert_reserved_usage_record(
                    session,
                    repo.ReservedUsageRecord(
                        request_id=params.request_id,
                        attempt_no=params.attempt_no,
                        scope=scope,
                        workspace_id=workspace_id,
                        task=params.task,
                        call_kind=params.call_kind,
                        provider=params.provider,
                        model=params.model,
                        catalog_version=params.catalog_version,
                        price_version=params.price_version,
                        billing_mode=params.billing_mode,
                        routing_version=params.routing_version,
                        route_rank=params.route_rank,
                        candidate_snapshot=params.candidate_snapshot,
                        reserved_micro_usd=estimate,
                        period_start=period,
                        started_at=now,
                    ),
                )
                return ReservationResult(record_id, budget_row_id, limit)

            if await repo.record_refusal(session, budget_row_id, limit, now):
                await self._publish_budget_event(session, budget_row_id, now, exhausted=True)
        # The transaction above has committed. Only now does the caller learn of the refusal.
        _log().info(
            "ai_budget_refused", scope=scope, task=params.task, period=period.isoformat()
        )
        raise AiBudgetExceeded()

    # ----------------------------------------------------------------------------------------
    # Settlement
    # ----------------------------------------------------------------------------------------

    async def settle_call(
        self,
        usage_record_id: UUID,
        budget_row_id: UUID,
        estimate_micro_usd: int,
        outcome: SettlementOutcome,
        limit_micro_usd: int,
    ) -> repo.SettleResult:
        """Settle one call in ONE transaction; publish the 80 % event in the same transaction.

        ``limit_micro_usd`` is the current configured limit (see ``limit_for_scope``). If the
        warning flag was newly set, ``ai.budget_threshold_reached`` and its audit record are written
        before commit. A failure of either, or ``BudgetRepositoryError`` from the repository, rolls
        everything back and propagates: the usage record stays ``reserved`` and the flag stays
        unset, so the caller can retry.
        """
        estimate = _check_amount("estimate_micro_usd", estimate_micro_usd)
        limit = _check_amount("limit_micro_usd", limit_micro_usd)
        now = self._clock.now()

        async with self._sessions() as session, session.begin():
            result = await repo.settle(
                session,
                usage_record_id,
                outcome.outcome,
                outcome.input_units,
                outcome.output_units,
                outcome.cost_micro_usd,
                outcome.error_code,
                outcome.finish_reason,
                outcome.schema_valid,
                outcome.validation_error_count,
                outcome.validation_error_types,
                outcome.latency_ms,
                budget_row_id,
                estimate,
                limit,
                now,
            )
            snapshot: repo.BudgetRowSnapshot | None = None
            if result.warning_newly_set:
                snapshot = await self._publish_budget_event(
                    session, budget_row_id, now, exhausted=False
                )
        if snapshot is not None:
            _log().warning(
                "ai_budget_threshold",
                scope=snapshot.scope,
                workspace_id=None if snapshot.workspace_id is None else str(snapshot.workspace_id),
                period=snapshot.period_start.isoformat(),
                limit_micro_usd=snapshot.limit_micro_usd,
                spent_micro_usd=snapshot.spent_micro_usd,
            )
        return result

    # ----------------------------------------------------------------------------------------
    # Event and audit (always inside the caller's open transaction)
    # ----------------------------------------------------------------------------------------

    async def _publish_budget_event(
        self,
        session: AsyncSession,
        budget_row_id: UUID,
        now: datetime,
        *,
        exhausted: bool,
    ) -> repo.BudgetRowSnapshot:
        snapshot = await repo.get_budget_row(session, budget_row_id)
        if snapshot is None:
            raise repo.BudgetRepositoryError("budget row missing when publishing its event")
        scope = _scope_literal(snapshot.scope)
        amounts: dict[str, Any] = {
            "scope": scope,
            "period_start": snapshot.period_start,
            "limit_micro_usd": snapshot.limit_micro_usd,
            "spent_micro_usd": snapshot.spent_micro_usd,
            "reserved_micro_usd": snapshot.reserved_micro_usd,
        }
        event: DomainEvent
        if exhausted:
            event = AiBudgetExhausted(
                aggregate_type=AI_BUDGET_AGGREGATE,
                aggregate_id=snapshot.id,
                workspace_id=snapshot.workspace_id,
                occurred_at=now,
                **amounts,
            )
        else:
            event = AiBudgetThresholdReached(
                aggregate_type=AI_BUDGET_AGGREGATE,
                aggregate_id=snapshot.id,
                workspace_id=snapshot.workspace_id,
                occurred_at=now,
                **amounts,
            )
        outbox_row = await self._publish(session, event)
        await append_audit(
            session,
            AuditRecord(
                actor_type=AUDIT_ACTOR_TYPE,
                action=EXHAUSTED_ACTION if exhausted else THRESHOLD_ACTION,
                resource_type=AUDIT_RESOURCE_TYPE,
                resource_id=str(snapshot.id),
                workspace_id=snapshot.workspace_id,
                request_id=f"ai_platform.budget:{snapshot.id}",
                event_id=outbox_row.event_id,
                occurred_at=now,
                details={
                    "budget_row_id": str(snapshot.id),
                    "scope": scope,
                    "period_start": snapshot.period_start.isoformat(),
                    "threshold_percent": 100 if exhausted else 80,
                    "limit_micro_usd": snapshot.limit_micro_usd,
                    "spent_micro_usd": snapshot.spent_micro_usd,
                    "reserved_micro_usd": snapshot.reserved_micro_usd,
                },
            ),
        )
        return snapshot


def _scope_literal(scope: str) -> repo.Scope:
    if scope == "workspace":
        return "workspace"
    if scope == "system":
        return "system"
    raise repo.BudgetRepositoryError("budget row has an unknown scope")


__all__ = [
    "AUDIT_ACTOR_TYPE",
    "AUDIT_RESOURCE_TYPE",
    "EXHAUSTED_ACTION",
    "THRESHOLD_ACTION",
    "BudgetCoordinator",
    "ReservationParams",
    "ReservationResult",
    "SettlementOutcome",
]
