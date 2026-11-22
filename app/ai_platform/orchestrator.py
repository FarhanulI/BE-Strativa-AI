"""AiOrchestrator.run (spec 5.2, 4.5), built up step by step in T-011.

Step 1: pre-routing validation. Nothing is written, reserved or called before it passes (spec 4.5).
Step 2: the sync request row (``running``), the Router call and the refusal endings. A call the
Router or the budget refuses ends the row ``failed`` with its ``error_code``, leaves no usage row
and no reservation, and raises the error class of ``errors.py``. A routable call stops at
``NotImplementedError`` until step 3 adds the provider call; its row stays ``running``.

The orchestrator never names a provider or model, and never puts request content into an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform import budget_repository as budget_repo
from app.ai_platform import request_repository as request_repo
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.context import AiCallContext
from app.ai_platform.enums import AiModality, LatencyClass, TaskScope
from app.ai_platform.errors import AiErrorCode, AiModalityNotSupported
from app.ai_platform.estimator import UnitEstimator
from app.ai_platform.messages import build_generation_messages
from app.ai_platform.provider import ProviderClient
from app.ai_platform.requests import AiTaskRequest, TextPart
from app.ai_platform.results import AiTaskResult
from app.ai_platform.router import (
    RoutingFailure,
    RoutingInput,
    RoutingResult,
    route,
    routing_error_class,
)
from app.ai_platform.schemas import OutputSchemaRegistry
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry, resolve_max_output_units
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
        request_id = await self._create_row(ctx, request, validated)

        parts_text = [part.text for part in request.parts if isinstance(part, TextPart)]
        messages, _marker = build_generation_messages(
            request.instructions, request.context, parts_text
        )
        input_units = self._estimator.estimate_messages(messages)
        routing = route(await self._routing_input(ctx, request, validated, input_units))
        if routing.failure is not None:
            await self._refuse(ctx, validated, request_id, routing, routing.failure)
        raise NotImplementedError("AiOrchestrator.run is built up step by step in T-011")

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
        async with self._sessions() as session, session.begin():
            await request_repo.complete_request(
                session,
                request_id,
                status="failed",
                error_code=_FAILURE_CODES[failure].value,
                routing_version=routing.routing_version,
                now=self._clock.now(),
            )
        raise routing_error_class(failure)()
