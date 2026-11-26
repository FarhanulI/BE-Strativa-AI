"""T-025 step 2: AC-21 (Router-time modality refusal on ``run``) and AC-51 (user path with a real
user), local Postgres.

* AC-21: ``run`` rejects a part modality the task does not allow before any row (unit tested). When
  the task allows the modality but no catalog model accepts it, the Router refuses: ``run`` raises
  ``AiModalityNotSupported``, the row ends ``failed`` with ``no_route`` (spec 4.5: no separate
  code), and there is no usage row, no reservation and no provider call.
* AC-51, ``run`` part: with a ``from_workspace`` context (a real ``users`` row, because
  ``requested_by_user_id`` is a foreign key) the interactive task succeeds, and a non-interactive
  task raises ``ValidationFailed`` with the fixed detail and leaves no row, usage or reservation.
  The ``submit`` clause of AC-51 is not covered (no ``submit``).
Synthetic text only.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.ai_platform import (
    AiCallContext,
    AiModalityNotSupported,
    AiTaskName,
    AiTaskRegistry,
    AiTaskRequest,
    ScriptedResponse,
)
from app.ai_platform.enums import AiModality
from app.ai_platform.orchestrator import ASYNC_ONLY_DETAIL
from app.ai_platform.requests import ImagePart, MediaRef
from app.ai_platform.tasks import AiTaskDefinition
from app.auth import User
from app.core import Settings, ValidationFailed
from app.workspace import WorkspaceContext, WorkspaceRole
from tests.helpers.ai_request_db_env import AiDbEnv, build_env
from tests.helpers.orchestrator_db import VALID_OUTPUT_JSON, build_orchestrator

pytestmark = pytest.mark.db

INTERACTIVE = AiTaskName.GENERATE_HOOK_VARIATIONS
NON_INTERACTIVE = AiTaskName.GENERATE_CONTENT_BRIEF


class _ImageTaskRegistry(AiTaskRegistry):
    """The built-in tasks, except that the interactive task also declares image input. The default
    synthetic catalog entry is text-only, so no model can take the image."""

    def get(self, task: AiTaskName) -> AiTaskDefinition:
        definition = super().get(task)
        if task is INTERACTIVE:
            return definition.model_copy(
                update={"input_modalities": frozenset({AiModality.TEXT, AiModality.IMAGE})}
            )
        return definition


@pytest.fixture
async def env(migrated_test_schema: Settings) -> AsyncIterator[AiDbEnv]:
    environment = build_env(migrated_test_schema)
    try:
        yield environment
    finally:
        try:
            async with environment.sessions() as session, session.begin():
                found = await session.execute(
                    text("SELECT id FROM ai_requests WHERE workspace_id = ANY(CAST(:w AS uuid[]))"),
                    {"w": environment.workspaces},
                )
                for (request_id,) in found.all():
                    if request_id not in environment.requests:
                        environment.requests.append(request_id)
            await environment.cleanup()
        finally:
            await environment.engine.dispose()


@pytest.fixture
async def user_id(env: AiDbEnv) -> AsyncIterator[UUID]:
    """A real ``users`` row. It depends on ``env``, so it is deleted before the environment's own
    teardown; the foreign key from ``ai_requests`` is SET NULL."""
    async with env.sessions() as session, session.begin():
        user = User(
            email=f"{uuid4()}@example.test",
            password_hash="$argon2id$test-only",
            display_name="ai-test",
            is_active=True,
        )
        session.add(user)
        await session.flush()
        created = user.id
    try:
        yield created
    finally:
        async with env.sessions() as session, session.begin():
            await session.execute(text("DELETE FROM users WHERE id = :u"), {"u": created})


async def _count(env: AiDbEnv, table: str, workspace_id: UUID) -> int:
    async with env.sessions() as session, session.begin():
        return int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE workspace_id = :w"),  # noqa: S608
                    {"w": workspace_id},
                )
            ).scalar_one()
        )


async def _reserved(env: AiDbEnv, workspace_id: UUID) -> int:
    async with env.sessions() as session, session.begin():
        return int(
            (
                await session.execute(
                    text(
                        "SELECT COALESCE(SUM(reserved_micro_usd), 0) FROM ai_budget_periods "
                        "WHERE workspace_id = :w"
                    ),
                    {"w": workspace_id},
                )
            ).scalar_one()
        )


async def test_a_modality_no_model_accepts_ends_the_row_failed_with_no_route(
    env: AiDbEnv,
) -> None:
    """AC-21: the task allows images, the catalog has none that accept them; the Router refuses."""
    workspace_id = await env.new_workspace()
    orchestrator, provider = build_orchestrator(
        env,
        env.clock(),
        tasks=_ImageTaskRegistry(),
        script=[ScriptedResponse.ok(VALID_OUTPUT_JSON)],
    )
    image = ImagePart(
        modality="image",
        media=MediaRef(kind="https_url", value="https://example.test/a.png"),
        mime_type="image/png",
    )
    with pytest.raises(AiModalityNotSupported):
        await orchestrator.run(
            AiCallContext.for_worker(workspace_id=workspace_id, request_id="r"),
            AiTaskRequest(task=INTERACTIVE, instructions="synthetic", parts=[image]),
        )
    async with env.sessions() as session, session.begin():
        (row,) = (
            await session.execute(
                text(
                    "SELECT status, error_code, completed_at FROM ai_requests "
                    "WHERE workspace_id = :w"
                ),
                {"w": workspace_id},
            )
        ).all()
    assert (row.status, row.error_code) == ("failed", "no_route") and row.completed_at is not None
    assert await _count(env, "ai_usage_records", workspace_id) == 0
    assert await _reserved(env, workspace_id) == 0
    assert provider.calls == ()


async def test_the_user_path_runs_the_interactive_task_and_refuses_the_others(
    env: AiDbEnv, user_id: UUID
) -> None:
    """AC-51 (``run`` part), INV-26, D-7: a user context succeeds on the interactive task, with
    the user recorded on the row; any other task is refused with the fixed detail and no trace."""
    workspace_id = await env.new_workspace()
    ctx = AiCallContext.from_workspace(
        WorkspaceContext(user_id=user_id, workspace_id=workspace_id, role=WorkspaceRole.MEMBER),
        request_id="r",
    )
    orchestrator, provider = build_orchestrator(
        env, env.clock(), script=[ScriptedResponse.ok(VALID_OUTPUT_JSON)]
    )
    await orchestrator.run(ctx, AiTaskRequest(task=INTERACTIVE, instructions="synthetic"))
    async with env.sessions() as session, session.begin():
        (row,) = (
            await session.execute(
                text(
                    "SELECT status, actor_type, requested_by_user_id FROM ai_requests "
                    "WHERE workspace_id = :w"
                ),
                {"w": workspace_id},
            )
        ).all()
    assert (row.status, row.actor_type, row.requested_by_user_id) == ("succeeded", "user", user_id)
    calls_before = len(provider.calls)

    with pytest.raises(ValidationFailed) as caught:
        await orchestrator.run(ctx, AiTaskRequest(task=NON_INTERACTIVE, instructions="synthetic"))
    assert caught.value.detail == ASYNC_ONLY_DETAIL
    assert await _count(env, "ai_requests", workspace_id) == 1  # no row for the refused call
    assert await _count(env, "ai_usage_records", workspace_id) == 1
    assert await _reserved(env, workspace_id) == 0
    assert len(provider.calls) == calls_before
