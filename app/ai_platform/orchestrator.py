"""AiOrchestrator.run (spec 5.2, 4.5), built up step by step in T-011.

Step 1: pre-routing validation. Nothing is written, reserved or called before it passes (spec 4.5).
Step 2: the sync request row (``running``), the Router call and the refusal endings. A call the
Router or the budget refuses ends the row ``failed`` with its ``error_code``, leaves no usage row
and no reservation, and raises the error class of ``errors.py``.
Step 3: one provider call on the first candidate: reserve the Router estimate unchanged (D-24),
call with no open transaction, the effective output cap (D-31) and the configured key (D-22),
validate strictly, settle, finish the row.
Step 4: fallback in rank order (spec 10.3). Every failed attempt is settled ``failed`` with its
``error_code`` and the next candidate is tried, up to ``max_provider_attempts`` distinct models.
Bad request and content refusal end the request at once. When the candidates or the attempt cap
are used up the error comes from ``final_error`` (D-32, observed behavior). When the time left
is below the next candidate's median latency the request fails ``provider_timeout``.
Step 5: the billing mode is locked by the Router (INV-29), so every candidate of a request has one
mode and a rate limit never crosses to the other mode; each attempt is recorded on the circuit
breaker. A candidate the breaker denies at call time is skipped: no attempt, no reservation, no
usage row (D-35). When every remaining candidate is skipped the request fails
``provider_unavailable``.
Step 6: a strict-validation failure gets up to ``max_repair_attempts`` repair calls to the same
model (spec 11): a new reservation from the repair messages, skipped without a call when it
exceeds the task's cost-class ceiling (D-34), no time is left or the breaker denies the model.
A truncated output is never repaired. The attempt cap counts distinct models, so a request makes
at most ``max_provider_attempts * (1 + max_repair_attempts)`` calls (INV-9).
T-023: any exception after the request row exists (an unexpected provider error, a failure while
settling, a cancellation) ends the row ``failed`` with ``execution_abandoned`` and abandons an
in-flight reservation at its estimate (INV-7, INV-14), then re-raises the original exception
unchanged. The cleanup is shielded from cancellation and is idempotent; if it fails, the reaper
(spec 4.5, 8.2) remains the backstop.

The orchestrator never names a provider or model, and never puts request content into an error.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NoReturn
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as budget_repo
from app.ai_platform import request_repository as request_repo
from app.ai_platform.budget_coordinator import (
    BudgetCoordinator,
    ReservationParams,
    ReservationResult,
    SettlementOutcome,
)
from app.ai_platform.catalog import CatalogModel, ModelCatalog
from app.ai_platform.circuit_breaker import AttemptHandle, CircuitBreakerRegistry
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.context import AiCallContext
from app.ai_platform.enums import AiModality, LatencyClass, TaskScope
from app.ai_platform.errors import (
    AiBudgetExceeded,
    AiErrorCode,
    AiModalityNotSupported,
    AiProviderUnavailable,
)
from app.ai_platform.estimator import UnitEstimator
from app.ai_platform.failure_policy import (
    ProviderFailureKind,
    classify,
    deadline_stop_error_code,
    final_error,
    next_attempt_allowed,
    terminal_error_class,
)
from app.ai_platform.messages import build_generation_messages, build_repair_messages
from app.ai_platform.pricing import cost_micro_usd, estimate_generation_micro_usd
from app.ai_platform.provider import (
    ChatMessage,
    ProviderCallError,
    ProviderClient,
    ProviderGenerationRequest,
    ProviderGenerationResponse,
    failure_kind_for_finish_reason,
)
from app.ai_platform.requests import AiTaskRequest, TextPart
from app.ai_platform.results import AiTaskResult
from app.ai_platform.router import (
    RoutedModel,
    RoutingFailure,
    RoutingInput,
    RoutingResult,
    route,
    routing_error_class,
)
from app.ai_platform.schemas import OutputSchemaRegistry
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry, resolve_max_output_units
from app.ai_platform.usage_types import AiUsageSummary
from app.ai_platform.validation import (
    ValidationIssue,
    ValidationOutcome,
    response_mode_for,
    response_schema_for,
    validate_output,
)
from app.core import Clock, ValidationFailed

# D-7: the fixed detail for a user-path `run` of a task that is not interactive.
ASYNC_ONLY_DETAIL = "This AI task must be submitted asynchronously"
# A call whose scope the task does not allow (spec 4.5, D-15). Fixed text, no request content.
SCOPE_NOT_ALLOWED_DETAIL = "This AI task is not available for this call scope"
# Recorded on ``ai_requests.routing_version``: the version of the rules of spec 10.2 that the
# Router implements. The spec fixes no value; change it when the rules change.
ROUTING_VERSION = "router-10.2-r1"

_FAILURE_CODES: dict[RoutingFailure, AiErrorCode] = {
    RoutingFailure.PROVIDER_NOT_CONFIGURED: AiErrorCode.PROVIDER_NOT_CONFIGURED,
    RoutingFailure.INPUT_TOO_LARGE: AiErrorCode.INPUT_TOO_LARGE,
    RoutingFailure.BUDGET_EXCEEDED: AiErrorCode.BUDGET_EXCEEDED,
    RoutingFailure.NO_ROUTE: AiErrorCode.NO_ROUTE,
    # A modality the task allows but no model can take: the spec lists no separate code (4.5).
    RoutingFailure.MODALITY_NOT_SUPPORTED: AiErrorCode.NO_ROUTE,
}


@dataclass(frozen=True, slots=True)
class ValidatedRun:
    """What pre-routing validation established; nothing here has touched the database."""

    task: AiTaskDefinition
    scope: TaskScope
    output_schema_version: int


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """One settled provider attempt. ``output`` is set only for a valid result; units and cost
    are what was settled on the usage row."""

    usage_record_id: UUID
    output: BaseModel | None
    input_units: int
    output_units: int
    cost_micro_usd: int
    error_code: AiErrorCode | None
    kind: ProviderFailureKind | None
    # Kept in memory only, for the repair message of a strict-validation failure. Never stored,
    # logged or put into an error (spec 11: only counts and type names are recorded).
    raw_text: str | None = None
    issues: tuple[ValidationIssue, ...] = ()


class AiOrchestrator:
    """Owns its own short transactions (spec 5.2, "Transaction ownership")."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        config: AiPlatformConfig,
        catalog: ModelCatalog,
        clock: Clock,
        breaker: CircuitBreakerRegistry,
        budgets: BudgetCoordinator,
        provider: ProviderClient,
        estimator: UnitEstimator,
        *,
        tasks: AiTaskRegistry | None = None,
        schemas: OutputSchemaRegistry | None = None,
    ) -> None:
        self._sessions = sessions
        self._config = config
        self._catalog = catalog
        self._clock = clock
        self._breaker = breaker
        self._budgets = budgets
        self._provider = provider
        self._estimator = estimator
        self._tasks = tasks if tasks is not None else AiTaskRegistry()
        self._schemas = schemas if schemas is not None else OutputSchemaRegistry()

    def validate_run(self, ctx: AiCallContext, request: AiTaskRequest) -> ValidatedRun:
        """Reject what needs no catalog and no budget (spec 4.5). Raises before any side effect.

        Order: unready task (INV-23), scope (D-15), user-path restriction (D-7, INV-26), modality.
        """
        task = self._tasks.get(request.task)
        if task.output_schema_name is None:  # EMBED_TEXT is never a generation task
            raise ValidationFailed(SCOPE_NOT_ALLOWED_DETAIL)
        version = (
            request.output_schema_version
            if request.output_schema_version is not None
            else task.default_output_schema_version
        )
        self._schemas.get(task.output_schema_name, version)  # AiTaskNotReady when unregistered
        scope = TaskScope.SYSTEM if ctx.is_system else TaskScope.WORKSPACE
        if scope not in task.allowed_scopes:
            raise ValidationFailed(SCOPE_NOT_ALLOWED_DETAIL)
        if ctx.actor_type == "user" and task.latency is not LatencyClass.INTERACTIVE:
            raise ValidationFailed(ASYNC_ONLY_DETAIL)
        allowed = task.input_modalities
        if any(AiModality(part.modality) not in allowed for part in request.parts):
            raise AiModalityNotSupported()
        return ValidatedRun(task=task, scope=scope, output_schema_version=version)

    async def run(self, ctx: AiCallContext, request: AiTaskRequest) -> AiTaskResult:
        validated = self.validate_run(ctx, request)
        started_at = self._clock.now()
        request_id = await self._create_row(ctx, request, validated)
        decided = _RoutingDecided()

        try:
            return await self._run_routed(ctx, request, validated, request_id, started_at, decided)
        except BaseException:
            # T-023 (D-A, D-C, D-D): end a row that is still running, then re-raise unchanged.
            # A deliberate ending already completed the row, so this is then a no-op.
            # T-024 D-C (b): the routing version is recorded only if routing made a decision.
            await self._fail_open_request(request_id, decided.routing_version)
            raise

    async def _run_routed(
        self,
        ctx: AiCallContext,
        request: AiTaskRequest,
        validated: ValidatedRun,
        request_id: UUID,
        started_at: datetime,
        decided: _RoutingDecided,
    ) -> AiTaskResult:
        """Route, attempt, validate and finish a request whose row already exists."""
        parts_text = [part.text for part in request.parts if isinstance(part, TextPart)]
        messages, marker = build_generation_messages(
            request.instructions, request.context, parts_text
        )
        input_units = self._estimator.estimate_messages(messages)
        routing = route(await self._routing_input(ctx, request, validated, input_units))
        decided.routing_version = routing.routing_version
        if routing.failure is not None:
            await self._refuse(ctx, validated, request_id, routing, routing.failure)

        attempts: list[AttemptResult] = []
        failures: list[ProviderFailureKind] = []
        tried = 0  # distinct models attempted; a repair call is not a new model
        cap = self._config.max_provider_attempts
        try:
            for candidate in routing.candidates:
                if tried >= cap:
                    break
                if tried and not self._may_try_next(candidate, started_at, validated, tried):
                    await self._end_failed(
                        request_id, deadline_stop_error_code(), routing.routing_version
                    )
                    raise AiProviderUnavailable()
                first = await self._guarded_attempt(
                    ctx,
                    request,
                    validated,
                    request_id,
                    routing,
                    candidate,
                    messages,
                    started_at,
                    attempt_no=len(attempts) + 1,
                    call_kind="generation",
                    reserve_micro_usd=candidate.estimated_cost_micro_usd,  # D-24
                )
                if first is None:
                    continue  # D-35: not an attempt, no reservation, no usage row
                tried += 1
                attempts.append(first)
                final = first
                for _ in range(self._config.max_repair_attempts):
                    if final.kind is not ProviderFailureKind.INVALID_OUTPUT:
                        break
                    repair = await self._repair(
                        ctx,
                        request,
                        validated,
                        request_id,
                        routing,
                        candidate,
                        messages,
                        marker,
                        final,
                        started_at,
                        attempt_no=len(attempts) + 1,
                    )
                    if repair is None:
                        break  # skipped: the candidate counts as failed (invalid output)
                    attempts.append(repair)
                    final = repair
                if final.kind is None:
                    break
                failures.append(final.kind)
                if classify(final.kind).terminal_on_first_failure:
                    await self._end_failed(
                        request_id, classify(final.kind).error_code, routing.routing_version
                    )
                    raise terminal_error_class(final.kind)()
        except AiBudgetExceeded:
            # The atomic reservation refused the call; its refusal was already recorded (D-33).
            # Budget exhaustion never falls back (spec 10.3).
            await self._end_failed(request_id, AiErrorCode.BUDGET_EXCEEDED, routing.routing_version)
            raise

        if not attempts:  # every candidate was denied by the breaker (D-35)
            await self._end_failed(
                request_id, AiErrorCode.PROVIDER_UNAVAILABLE, routing.routing_version
            )
            raise AiProviderUnavailable()
        last = attempts[-1]
        if last.output is None:
            ended = final_error(failures)
            await self._end_failed(request_id, ended.error_code, routing.routing_version)
            raise ended.error_class()

        output = last.output
        await self._end_succeeded(request_id, request, output, routing.routing_version)
        return AiTaskResult(
            request_id=request_id,
            task=validated.task.name,
            output=output,
            output_schema_name=_required(validated.task.output_schema_name),
            output_schema_version=validated.output_schema_version,
            usage=AiUsageSummary(
                input_units=sum(a.input_units for a in attempts),
                output_units=sum(a.output_units for a in attempts),
                cost_micro_usd=sum(a.cost_micro_usd for a in attempts),
                call_count=len(attempts),
            ),
            routing_id=last.usage_record_id,
        )

    def _remaining_ms(self, validated: ValidatedRun, started_at: datetime) -> int:
        remaining = (
            self._config.deadline_seconds(validated.task.latency)
            - (self._clock.now() - started_at).total_seconds()
        )
        return max(0, int(remaining * 1000))

    def _may_try_next(
        self, candidate: RoutedModel, started_at: datetime, validated: ValidatedRun, tried: int
    ) -> bool:
        """The deadline rule of spec 10.3: the time left must cover the next model's p50."""
        return next_attempt_allowed(
            tried,
            self._config.max_provider_attempts,
            self._remaining_ms(validated, started_at),
            self._entry(candidate).latency_p50_ms,
        )

    def _padded_input(self, units: int) -> int:
        """``ceil(units * (100 + margin) / 100)``, the same margin as the Router (spec 10.2.3)."""
        margin = self._config.context_safety_margin_percent
        return -(-(units * (100 + margin)) // 100)

    async def _guarded_attempt(
        self,
        ctx: AiCallContext,
        request: AiTaskRequest,
        validated: ValidatedRun,
        request_id: UUID,
        routing: RoutingResult,
        candidate: RoutedModel,
        messages: tuple[ChatMessage, ...],
        started_at: datetime,
        *,
        attempt_no: int,
        call_kind: Literal["generation", "repair"],
        reserve_micro_usd: int,
    ) -> AttemptResult | None:
        """One attempt behind the breaker. ``None`` when the breaker denies the model (D-35)."""
        handle = self._breaker.begin_attempt((candidate.provider, candidate.model))
        if handle is None:
            return None
        try:
            return await self._attempt(
                ctx,
                request,
                validated,
                request_id,
                routing,
                candidate,
                messages,
                started_at,
                handle,
                attempt_no=attempt_no,
                call_kind=call_kind,
                reserve_micro_usd=reserve_micro_usd,
            )
        except BaseException:
            # T-022 (D-37): release the probe this handle owns. A failing release must not replace
            # the original exception; the probe lease expiry is the backstop for a lost release.
            with contextlib.suppress(Exception):
                self._breaker.abandon_attempt(handle)
            raise

    async def _repair(
        self,
        ctx: AiCallContext,
        request: AiTaskRequest,
        validated: ValidatedRun,
        request_id: UUID,
        routing: RoutingResult,
        candidate: RoutedModel,
        messages: tuple[ChatMessage, ...],
        marker: str,
        failed: AttemptResult,
        started_at: datetime,
        *,
        attempt_no: int,
    ) -> AttemptResult | None:
        """One repair call to the same model (spec 11, D-34); ``None`` when it is skipped.

        The reservation is a new one from the margin-padded repair messages and the same effective
        output cap. It is skipped, without a provider call, when it exceeds the task's cost-class
        ceiling, when the time left is below the model's median latency, or when the breaker
        denies the model.
        """
        entry = self._entry(candidate)
        if candidate.effective_max_output_units is None:
            raise ValueError("a generation candidate needs an effective output cap")
        repair_messages = build_repair_messages(
            messages, failed.raw_text or "", failed.issues, marker
        )
        estimate = estimate_generation_micro_usd(
            self._padded_input(self._estimator.estimate_messages(repair_messages)),
            candidate.effective_max_output_units,
            entry,
        )
        if estimate > self._config.cost_ceiling_micro_usd(validated.task.cost):
            return None
        if self._remaining_ms(validated, started_at) < entry.latency_p50_ms:
            return None
        return await self._guarded_attempt(
            ctx,
            request,
            validated,
            request_id,
            routing,
            candidate,
            repair_messages,
            started_at,
            attempt_no=attempt_no,
            call_kind="repair",
            reserve_micro_usd=estimate,
        )

    async def _attempt(
        self,
        ctx: AiCallContext,
        request: AiTaskRequest,
        validated: ValidatedRun,
        request_id: UUID,
        routing: RoutingResult,
        candidate: RoutedModel,
        messages: tuple[ChatMessage, ...],
        started_at: datetime,
        handle: AttemptHandle,
        *,
        attempt_no: int,
        call_kind: Literal["generation", "repair"],
        reserve_micro_usd: int,
    ) -> AttemptResult:
        """Reserve, call and settle once: three separate steps, no transaction open in the call."""
        task = validated.task
        scope: budget_repo.Scope = (
            "workspace" if validated.scope is TaskScope.WORKSPACE else "system"
        )
        entry = self._entry(candidate)
        schema = self._schemas.get(
            _required(task.output_schema_name), validated.output_schema_version
        )
        if candidate.effective_max_output_units is None:
            raise ValueError("a generation candidate needs an effective output cap")

        # Reserve the given estimate: the Router's, unchanged, for a first call (D-24), or the
        # repair estimate (D-34). Own transaction, committed on return.
        reservation = await self._budgets.reserve_for_call(
            scope,
            ctx.workspace_id,
            reserve_micro_usd,
            ReservationParams(
                request_id=request_id,
                attempt_no=attempt_no,
                task=task.name.value,
                call_kind=call_kind,
                provider=candidate.provider,
                model=candidate.model,
                catalog_version=self._catalog.catalog_version,
                price_version=self._catalog.price_version,
                billing_mode=candidate.billing_mode,
                routing_version=routing.routing_version,
                route_rank=candidate.route_rank,
                candidate_snapshot=routing.snapshot,
            ),
        )

        try:
            return await self._call_and_settle(
                task,
                entry,
                schema,
                candidate,
                messages,
                started_at,
                handle,
                reservation,
                reserve_micro_usd,
            )
        except BaseException:
            # T-023 (D-B): the call was reserved but not settled. Abandon it at its estimate
            # (INV-14) so no reservation is left behind, then re-raise unchanged. A record that
            # was settled meanwhile is left alone.
            await self._finish_shielded(self._budgets.abandon_call(reservation.usage_record_id))
            raise

    async def _call_and_settle(
        self,
        task: AiTaskDefinition,
        entry: CatalogModel,
        schema: type[BaseModel],
        candidate: RoutedModel,
        messages: tuple[ChatMessage, ...],
        started_at: datetime,
        handle: AttemptHandle,
        reservation: ReservationResult,
        reserve_micro_usd: int,
    ) -> AttemptResult:
        """The provider call and the settlement of one reserved attempt (no transaction open
        during the call)."""
        remaining = (
            self._config.deadline_seconds(task.latency)
            - (self._clock.now() - started_at).total_seconds()
        )
        provider_request = ProviderGenerationRequest(
            provider=candidate.provider,
            model=candidate.model,
            messages=messages,
            response_mode=response_mode_for(entry.supports_json_schema),
            response_schema=response_schema_for(schema),
            max_output_units=candidate.effective_max_output_units,  # D-26, D-31
            timeout_seconds=max(remaining, 0.001),
        )
        call_started = self._clock.now()
        response: ProviderGenerationResponse | None = None
        failure: ProviderCallError | None = None
        try:
            response = await self._provider.generate(
                provider_request, api_key=self._config.api_key_for(candidate.provider)
            )
        except ProviderCallError as error:
            failure = error
        latency_ms = int((self._clock.now() - call_started).total_seconds() * 1000)

        outcome: ValidationOutcome | None = None
        kind: ProviderFailureKind | None = None
        if failure is not None:
            kind = failure.kind
            input_units, output_units = failure.input_units or 0, failure.output_units or 0
        else:
            assert response is not None
            input_units = (
                response.input_units
                if response.input_units is not None
                else self._estimator.estimate_messages(messages)
            )
            output_units = (
                response.output_units
                if response.output_units is not None
                else self._estimator.estimate_text(response.raw_text)
            )
            kind = failure_kind_for_finish_reason(response.finish_reason)
            if kind is None:
                outcome = validate_output(response.raw_text, schema)
                if not outcome.ok:
                    kind = ProviderFailureKind.INVALID_OUTPUT
        cost = cost_micro_usd(
            input_units, entry.input_micro_usd_per_million_units
        ) + cost_micro_usd(output_units, entry.output_micro_usd_per_million_units)
        error_code = None if kind is None else classify(kind).error_code
        if kind is None:
            self._breaker.record_success(handle)
        else:
            self._breaker.record_failure(handle, kind)
        finish = None if response is None else response.finish_reason

        await self._budgets.settle_call(
            reservation.usage_record_id,
            reservation.budget_row_id,
            reserve_micro_usd,
            SettlementOutcome(
                outcome="succeeded" if kind is None else "failed",
                input_units=input_units,
                output_units=output_units,
                cost_micro_usd=cost,
                error_code=None if error_code is None else error_code.value,
                finish_reason=finish,
                schema_valid=None if outcome is None else outcome.ok,
                validation_error_count=(
                    outcome.error_count if outcome is not None and not outcome.ok else None
                ),
                validation_error_types=(
                    list(outcome.error_types) if outcome is not None and not outcome.ok else None
                ),
                latency_ms=latency_ms,
            ),
            reservation.limit_micro_usd,
        )
        return AttemptResult(
            usage_record_id=reservation.usage_record_id,
            output=outcome.instance if outcome is not None and kind is None else None,
            input_units=input_units,
            output_units=output_units,
            cost_micro_usd=cost,
            error_code=error_code,
            kind=kind,
            raw_text=(
                response.raw_text
                if response is not None and outcome is not None and not outcome.ok
                else None
            ),
            issues=outcome.issues if outcome is not None and not outcome.ok else (),
        )

    async def _fail_open_request(self, request_id: UUID, routing_version: str | None) -> None:
        """End the row ``failed`` with ``execution_abandoned`` if it is still ``running``.

        The completion is one conditional UPDATE, so a row that was already ended (a deliberate
        refusal or failure) is left as it is. Shielded from cancellation (T-023 D-D).
        ``routing_version`` is ``None`` when the fault came before routing decided (T-024 D-C):
        the column then stays NULL.
        """
        await self._finish_shielded(
            self._end_failed(request_id, AiErrorCode.EXECUTION_ABANDONED, routing_version)
        )

    @staticmethod
    async def _finish_shielded(work: Awaitable[object]) -> None:
        """Run cleanup to completion even when the calling task is cancelled meanwhile.

        Further cancellations are held until the cleanup is done; the caller re-raises the
        original exception afterwards. An error in the cleanup itself is dropped, because the
        original exception matters more and the reaper (spec 4.5) cleans up what is left.
        """
        inner = asyncio.ensure_future(work)
        while not inner.done():
            try:
                await asyncio.shield(inner)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if inner.done() and not inner.cancelled():
            inner.exception()  # mark a dropped error as retrieved

    def _entry(self, candidate: RoutedModel) -> CatalogModel:
        for entry in self._catalog.models():
            if (entry.provider, entry.model) == (candidate.provider, candidate.model):
                return entry
        raise ValueError("the routed model is not in the catalog")

    # ----------------------------------------------------------------------------------------
    # Row lifecycle and routing input (each database step is its own short transaction)
    # ----------------------------------------------------------------------------------------

    async def _create_row(
        self, ctx: AiCallContext, request: AiTaskRequest, validated: ValidatedRun
    ) -> UUID:
        async with self._sessions() as session, session.begin():
            return await request_repo.insert_sync_request(
                session,
                scope=validated.scope.value,
                workspace_id=ctx.workspace_id,
                requested_by_user_id=ctx.user_id,
                actor_type=ctx.actor_type,
                task=validated.task.name.value,
                output_schema_name=validated.task.output_schema_name,
                output_schema_version=validated.output_schema_version,
                correlation_request_id=ctx.request_id,
                now=self._clock.now(),
                instructions_version=request.instructions_version,
            )

    async def _remaining_budget(self, ctx: AiCallContext, validated: ValidatedRun) -> int:
        """``limit - spent - reserved`` of the row this call uses, as a snapshot (spec 10.2.7)."""
        limit = self._budgets.limit_for_scope(validated.scope.value)
        if ctx.workspace_id is None:  # system scope serves only EMBED_TEXT, never `run`
            raise ValueError("run needs a workspace-scope context")
        async with self._sessions() as session, session.begin():
            row = await budget_repo.find_workspace_budget_row(
                session, ctx.workspace_id, budget_repo.period_start_for(self._clock.now())
            )
        if row is None:
            return limit
        return max(0, limit - row.spent_micro_usd - row.reserved_micro_usd)

    async def _routing_input(
        self,
        ctx: AiCallContext,
        request: AiTaskRequest,
        validated: ValidatedRun,
        input_units: int,
    ) -> RoutingInput:
        task = validated.task
        providers = {entry.provider for entry in self._catalog.models()}
        configured = self._config.provider_configured_map(providers)
        modes = self._config.billing_mode_map(p for p in providers if configured[p])
        return RoutingInput(
            task=task,
            input_modalities_present=frozenset({AiModality.TEXT})
            | frozenset(AiModality(part.modality) for part in request.parts),
            estimated_input_units=input_units,
            context_safety_margin_percent=self._config.context_safety_margin_percent,
            max_output_units=resolve_max_output_units(task, request.max_output_units),
            quality_floor=request.quality_floor,
            cost_ceiling_micro_usd=self._config.cost_ceiling_micro_usd(task.cost),
            remaining_budget_micro_usd=await self._remaining_budget(ctx, validated),
            provider_configured=configured,
            provider_billing_mode=modes,
            unavailable_models=self._breaker.unavailable_models(),
            routing_version=ROUTING_VERSION,
            catalog=self._catalog,
        )

    async def _refuse(
        self,
        ctx: AiCallContext,
        validated: ValidatedRun,
        request_id: UUID,
        routing: RoutingResult,
        failure: RoutingFailure,
    ) -> NoReturn:
        """End the row ``failed`` and raise. A budget refusal goes through D-33 first."""
        if failure is RoutingFailure.BUDGET_EXCEEDED:
            await self._budgets.refuse_for_call(
                validated.scope.value, ctx.workspace_id, validated.task.name.value
            )
        await self._end_failed(request_id, _FAILURE_CODES[failure], routing.routing_version)
        raise routing_error_class(failure)()

    async def _end_failed(
        self, request_id: UUID, error_code: AiErrorCode, routing_version: str | None
    ) -> None:
        async with self._sessions() as session, session.begin():
            await request_repo.complete_request(
                session,
                request_id,
                status="failed",
                error_code=error_code.value,
                routing_version=routing_version,
                now=self._clock.now(),
            )

    async def _end_succeeded(
        self,
        request_id: UUID,
        request: AiTaskRequest,
        output: BaseModel,
        routing_version: str,
    ) -> None:
        """Finish ``succeeded``; the output is stored only when the caller asked (spec 4.5)."""
        async with self._sessions() as session, session.begin():
            await request_repo.complete_request(
                session,
                request_id,
                status="succeeded",
                error_code=None,
                output_payload=output.model_dump(mode="json") if request.persist_result else None,
                routing_version=routing_version,
                now=self._clock.now(),
            )


class _RoutingDecided:
    """Whether routing has made a decision for one ``run`` call, and under which rules version.

    Set once routing returns; ``None`` before that, so a fault ahead of routing leaves
    ``ai_requests.routing_version`` NULL (T-024 D-C).
    """

    __slots__ = ("routing_version",)

    def __init__(self) -> None:
        self.routing_version: str | None = None


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("a generation task has an output schema")
    return value
