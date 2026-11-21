"""AiOrchestrator.run (spec 5.2, 4.5). T-011 step 1: construction and pre-routing validation only.

Everything here happens before any row is written, any reservation is made or any provider is
called (spec 4.5, "Validation before routing"). The routed part of ``run`` is added by the later
steps of T-011; until then a request that passes validation stops at ``NotImplementedError``.

The orchestrator never names a provider or model, and never puts request content into an error.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.config import AiPlatformConfig
from app.ai_platform.context import AiCallContext
from app.ai_platform.enums import AiModality, LatencyClass, TaskScope
from app.ai_platform.errors import AiModalityNotSupported
from app.ai_platform.provider import ProviderClient
from app.ai_platform.requests import AiTaskRequest
from app.ai_platform.results import AiTaskResult
from app.ai_platform.schemas import OutputSchemaRegistry
from app.ai_platform.tasks import AiTaskDefinition, AiTaskRegistry
from app.core import Clock, ValidationFailed

# D-7: the fixed detail for a user-path `run` of a task that is not interactive.
ASYNC_ONLY_DETAIL = "This AI task must be submitted asynchronously"
# A call whose scope the task does not allow (spec 4.5, D-15). Fixed text, no request content.
SCOPE_NOT_ALLOWED_DETAIL = "This AI task is not available for this call scope"


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
        self.validate_run(ctx, request)
        raise NotImplementedError("AiOrchestrator.run is built up step by step in T-011")
