"""AiCallContext constructors, identifier boundary and construction guard (5.1, AC-12)."""

from __future__ import annotations

import dataclasses
from uuid import UUID, uuid4

import pytest

from app.ai_platform import AiCallContext
from app.workspace import WorkspaceContext, WorkspaceRole


def _workspace_context() -> WorkspaceContext:
    return WorkspaceContext(user_id=uuid4(), workspace_id=uuid4(), role=WorkspaceRole.MEMBER)


def test_from_workspace_takes_the_verified_uuids() -> None:
    workspace = _workspace_context()
    ctx = AiCallContext.from_workspace(workspace, request_id="req-1")
    assert ctx.workspace_id == workspace.workspace_id
    assert ctx.user_id == workspace.user_id
    assert isinstance(ctx.workspace_id, UUID)
    assert isinstance(ctx.user_id, UUID)
    assert ctx.actor_type == "user"
    assert ctx.request_id == "req-1"
    assert ctx.is_system is False


@pytest.mark.parametrize("bad", [uuid4(), str(uuid4()), None, {"workspace_id": "x"}])
def test_from_workspace_rejects_anything_but_a_workspace_context(bad: object) -> None:
    with pytest.raises(TypeError):
        AiCallContext.from_workspace(bad, request_id="r")  # type: ignore[arg-type]


def test_for_worker_has_a_workspace_and_no_user() -> None:
    workspace_id = uuid4()
    ctx = AiCallContext.for_worker(workspace_id=workspace_id, request_id="req-2")
    assert ctx.workspace_id == workspace_id
    assert ctx.user_id is None
    assert ctx.actor_type == "worker"
    assert ctx.is_system is False


@pytest.mark.parametrize("bad", [None, str(uuid4()), 7, b"x"])
def test_for_worker_rejects_none_and_non_uuid(bad: object) -> None:
    with pytest.raises(ValueError):
        AiCallContext.for_worker(workspace_id=bad, request_id="r")  # type: ignore[arg-type]


def test_system_has_no_workspace_and_no_user() -> None:
    ctx = AiCallContext.system(request_id="req-3")
    assert ctx.workspace_id is None
    assert ctx.user_id is None
    assert ctx.actor_type == "system"
    assert ctx.is_system is True


def test_direct_construction_is_refused() -> None:
    with pytest.raises(TypeError):
        AiCallContext(workspace_id=uuid4(), user_id=None, actor_type="worker", request_id="r")
    with pytest.raises(TypeError):
        AiCallContext(None, None, "system", "r")
    with pytest.raises(TypeError):
        AiCallContext(None, None, "system", "r", _factory_guard=object())  # type: ignore[call-arg]


@pytest.mark.parametrize("bad", ["", None, 5])
def test_request_id_must_be_a_non_empty_string(bad: object) -> None:
    with pytest.raises(ValueError):
        AiCallContext.system(request_id=bad)  # type: ignore[arg-type]


def test_context_is_frozen_and_has_exactly_the_spec_fields() -> None:
    ctx = AiCallContext.system(request_id="r")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.workspace_id = uuid4()  # type: ignore[misc]
    assert [f.name for f in dataclasses.fields(AiCallContext)] == [
        "workspace_id",
        "user_id",
        "actor_type",
        "request_id",
    ]
