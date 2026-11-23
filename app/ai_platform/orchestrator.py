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
is below the next candidate's median latency the request fails ``provider_timeout``. A strict
validation failure falls back without a repair call until step 6; the circuit breaker is used
from step 5.

The orchestrator never names a provider or model, and never puts request content into an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as budget_repo
from app.ai_platform import request_repository as request_repo
from app.ai_platform.budget_coordinator import (
    BudgetCoordinator,
    ReservationParams,
    SettlementOutcome,
)
from app.ai_platform.catalog import CatalogModel, ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
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
from app.ai_platform.messages import build_generation_messages
from app.ai_platform.pricing import cost_micro_usd
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

        parts_text = [part.text for part in request.parts if isinstance(part, TextPart)]
        messages, _marker = build_generation_messages(
            request.instructions, request.context, parts_text
        )
        input_units = self._estimator.estimate_messages(messages)
        routing = route(await self._routing_input(ctx, request, validated, input_units))
        if routing.failure is not None:
            await self._refuse(ctx, validated, request_id, routing, routing.failure)

        attempts: list[AttemptResult] = []
        failures: list[ProviderFailureKind] = []
        cap = self._config.max_provider_attempts
        try:
            for index, candidate in enumerate(routing.candidates[:cap]):
                if index > 0 and not self._may_try_next(candidate, started_at, validated, index):
                    await self._end_failed(
                        request_id, deadline_stop_error_code(), routing.routing_version
                    )
                    raise AiProviderUnavailable()
                attempt = await self._attempt(
                    ctx,
                    request,
                    validated,
                    request_id,
                    routing,
                    candidate,
                    messages,
                    started_at,
                    attempt_no=len(attempts) + 1,
                )
                attempts.append(attempt)
                if attempt.kind is None:
                    break
                failures.append(attempt.kind)
                if classify(attempt.kind).terminal_on_first_failure:
                    await self._end_failed(
                        request_id, classify(attempt.kind).error_code, routing.routing_version
                    )
                    raise terminal_error_class(attempt.kind)()
        except AiBudgetExceeded:
            # The atomic reservation refused the call; its refusal was already recorded (D-33).
            # Budget exhaustion never falls back (spec 10.3).
            await self._end_failed(request_id, AiErrorCode.BUDGET_EXCEEDED, routing.routing_version)
            raise

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

    def _may_try_next(
        self, candidate: RoutedModel, started_at: datetime, validated: ValidatedRun, tried: int
    ) -> bool:
        """The deadline rule of spec 10.3: the time left must cover the next model's p50."""
        remaining = (
            self._config.deadline_seconds(validated.task.latency)
            - (self._clock.now() - started_at).total_seconds()
        )
        return next_attempt_allowed(
            tried,
            self._config.max_provider_attempts,
            max(0, int(remaining * 1000)),
            self._entry(candidate).latency_p50_ms,
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
        *,
        attempt_no: int,
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

        # Reserve the Router's estimate, unchanged (D-24). Own transaction, committed on return.
        reservation = await self._budgets.reserve_for_call(
            scope,
            ctx.workspace_id,
            candidate.estimated_cost_micro_usd,
            ReservationParams(
                request_id=request_id,
                attempt_no=attempt_no,
                task=task.name.value,
                call_kind="generation",
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
        finish = None if response is None else response.finish_reason

        await self._budgets.settle_call(
            reservation.usage_record_id,
            reservation.budget_row_id,
            candidate.estimated_cost_micro_usd,
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
        )

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
        self, request_id: UUID, error_code: AiErrorCode, routing_version: str
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


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("a generation task has an output schema")
    return value
