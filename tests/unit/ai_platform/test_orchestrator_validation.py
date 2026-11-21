"""T-011 step 1: pre-routing validation of ``AiOrchestrator.run`` (unit only, no database).

Covers the ``run`` rejections of INV-23 / AC-26 (unready task), INV-26 / AC-51 (user-path
restriction, D-7), the scope rule (D-15) and AC-21's modality rejection (spec 4.5). Each rejected
call must leave nothing behind: the session factory is a trap that fails the test if it is touched,
and the fake provider must have received zero calls. Synthetic text only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.ai_platform import (
    AiCallContext,
    AiModalityNotSupported,
    AiPlatformConfig,
    AiTaskName,
    AiTaskNotReady,
    AiTaskRegistry,
    AiTaskRequest,
    FakeAiProvider,
    OutputSchemaRegistry,
)
from app.ai_platform.budget_coordinator import BudgetCoordinator
from app.ai_platform.catalog import ModelCatalog
from app.ai_platform.circuit_breaker import CircuitBreakerRegistry
from app.ai_platform.orchestrator import (
    ASYNC_ONLY_DETAIL,
    SCOPE_NOT_ALLOWED_DETAIL,
    AiOrchestrator,
)
from app.ai_platform.requests import ImagePart, MediaRef, TextPart
from app.core import FakeClock, ValidationFailed
from app.workspace import WorkspaceContext, WorkspaceRole
from tests.helpers.synthetic_catalog import catalog_dict

INTERACTIVE = AiTaskName.GENERATE_HOOK_VARIATIONS
NON_INTERACTIVE = AiTaskName.GENERATE_CONTENT_BRIEF  # latency class "standard"
BATCH = AiTaskName.SYNTHESIZE_SIGNALS


class _Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = ""


class _SessionTrap:
    """Stands in for ``async_sessionmaker``: any use means a database was reached."""

    calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        type(self).calls += 1
        raise AssertionError("pre-routing validation must not open a database session")


def _schemas(*names: str) -> OutputSchemaRegistry:
    registry = OutputSchemaRegistry()
    for name in names:
        registry.register(name, 1, _Output)
    return registry


def _all_schemas() -> OutputSchemaRegistry:
    return _schemas(
        *(t.output_schema_name for t in AiTaskRegistry().list() if t.output_schema_name)
    )


def _build(
    schemas: OutputSchemaRegistry | None = None,
) -> tuple[AiOrchestrator, FakeAiProvider, _SessionTrap]:
    _SessionTrap.calls = 0
    trap = _SessionTrap()
    config = AiPlatformConfig(_env_file=None)  # type: ignore[call-arg]
    clock = FakeClock(datetime(2026, 11, 21, 12, 0, tzinfo=UTC))
    provider = FakeAiProvider()
    orchestrator = AiOrchestrator(
        trap,  # type: ignore[arg-type]
        config,
        ModelCatalog.from_dict(catalog_dict()),
        clock,
        CircuitBreakerRegistry(clock, config),
        BudgetCoordinator(trap, clock, config),  # type: ignore[arg-type]
        provider,
        schemas=schemas if schemas is not None else _all_schemas(),
    )
    return orchestrator, provider, trap


def _user_ctx() -> AiCallContext:
    workspace = WorkspaceContext(user_id=uuid4(), workspace_id=uuid4(), role=WorkspaceRole.MEMBER)
    return AiCallContext.from_workspace(workspace, request_id="req-1")


def _worker_ctx() -> AiCallContext:
    return AiCallContext.for_worker(workspace_id=uuid4(), request_id="req-2")


def _request(task: AiTaskName = INTERACTIVE, **overrides: Any) -> AiTaskRequest:
    return AiTaskRequest(task=task, instructions="synthetic instructions", **overrides)


def _assert_nothing_happened(provider: FakeAiProvider, trap: _SessionTrap) -> None:
    assert provider.calls == ()
    assert trap.calls == 0


async def test_unregistered_schema_raises_task_not_ready_without_any_call() -> None:
    """INV-23, AC-26: a task without a registered output schema fails closed."""
    orchestrator, provider, trap = _build(schemas=_schemas())
    with pytest.raises(AiTaskNotReady):
        await orchestrator.run(_worker_ctx(), _request())
    _assert_nothing_happened(provider, trap)


async def test_pinned_unregistered_schema_version_raises_task_not_ready() -> None:
    """Spec 11: a request for an unregistered output schema version is AiTaskNotReady."""
    orchestrator, provider, trap = _build()
    with pytest.raises(AiTaskNotReady):
        await orchestrator.run(_worker_ctx(), _request(output_schema_version=7))
    _assert_nothing_happened(provider, trap)


async def test_user_path_run_of_a_non_interactive_task_is_refused_with_the_fixed_detail() -> None:
    """INV-26, AC-51, D-7: ValidationFailed with the fixed text, before any session or provider."""
    orchestrator, provider, trap = _build()
    for task in (NON_INTERACTIVE, BATCH):
        with pytest.raises(ValidationFailed) as caught:
            await orchestrator.run(_user_ctx(), _request(task))
        assert (
            caught.value.detail
            == ASYNC_ONLY_DETAIL
            == ("This AI task must be submitted asynchronously")
        )
    _assert_nothing_happened(provider, trap)


async def test_user_path_run_of_the_interactive_task_passes_validation() -> None:
    """AC-51: GENERATE_HOOK_VARIATIONS is interactive, so validation accepts a user context.

    The routed part of ``run`` does not exist yet, so the call stops at NotImplementedError,
    which proves validation did not reject it. The full success is tested in step 3.
    """
    orchestrator, provider, trap = _build()
    with pytest.raises(NotImplementedError):
        await orchestrator.run(_user_ctx(), _request(INTERACTIVE))
    _assert_nothing_happened(provider, trap)


@pytest.mark.parametrize("task", [NON_INTERACTIVE, BATCH, INTERACTIVE])
async def test_worker_context_passes_validation_for_any_task(task: AiTaskName) -> None:
    """AC-51: the same non-interactive task is allowed through ``for_worker``."""
    orchestrator, provider, trap = _build()
    validated = orchestrator.validate_run(_worker_ctx(), _request(task))
    assert validated.task.name is task
    with pytest.raises(NotImplementedError):
        await orchestrator.run(_worker_ctx(), _request(task))
    _assert_nothing_happened(provider, trap)


@pytest.mark.parametrize(
    "task", [t for t in AiTaskRegistry().list() if t.output_schema_name is not None]
)
async def test_system_scope_is_rejected_for_every_generation_task(task: Any) -> None:
    """D-15: a system-scope call for a task that does not list ``system`` is rejected."""
    orchestrator, provider, trap = _build()
    ctx = AiCallContext.system(request_id="req-sys")
    with pytest.raises(ValidationFailed) as caught:
        await orchestrator.run(ctx, _request(task.name))
    assert caught.value.detail == SCOPE_NOT_ALLOWED_DETAIL
    _assert_nothing_happened(provider, trap)


async def test_image_part_on_a_text_only_task_is_a_modality_error() -> None:
    """AC-21 (rejection part), spec 4.5: a part modality outside the task definition."""
    orchestrator, provider, trap = _build()
    part = ImagePart(
        modality="image",
        media=MediaRef(kind="https_url", value="https://example.test/a.png"),
        mime_type="image/png",
    )
    with pytest.raises(AiModalityNotSupported):
        await orchestrator.run(_worker_ctx(), _request(parts=[part]))
    _assert_nothing_happened(provider, trap)


async def test_text_part_on_a_text_task_is_accepted() -> None:
    orchestrator, provider, trap = _build()
    request = _request(parts=[TextPart(modality="text", text="synthetic")])
    assert orchestrator.validate_run(_worker_ctx(), request).task.name is INTERACTIVE
    _assert_nothing_happened(provider, trap)


async def test_validated_run_resolves_the_default_schema_version_and_scope() -> None:
    orchestrator, _provider, _trap = _build()
    validated = orchestrator.validate_run(_worker_ctx(), _request())
    assert validated.output_schema_version == 1
    assert validated.scope.value == "workspace"


async def test_rejection_messages_carry_no_request_content() -> None:
    """No prompt or context text in an error (INV-24 hygiene for the pre-routing errors)."""
    orchestrator, provider, trap = _build()
    sentinel = "zz-sentinel-instructions-4417"
    request = AiTaskRequest(task=NON_INTERACTIVE, instructions=sentinel)
    with pytest.raises(ValidationFailed) as caught:
        await orchestrator.run(_user_ctx(), request)
    assert sentinel not in str(caught.value) and sentinel not in caught.value.detail
    _assert_nothing_happened(provider, trap)
