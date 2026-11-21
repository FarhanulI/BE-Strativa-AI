"""AiCallContext: who an AI call is for (spec 5.1, INV-19, INV-31).

The three classmethods are the only way to build a context. The normal constructor refuses use
outside them: it requires a private guard object that only the classmethods hold, so a module that
writes ``AiCallContext(...)`` directly fails at once. (An architecture test also scans every module
outside ``app/ai_platform`` and ``app/rag`` for direct construction and for
``AiCallContext.system``.)

Identifiers are ``UUID`` at this boundary. ``from_workspace`` takes an already-verified
``WorkspaceContext``; ``for_worker`` takes a workspace id read from persisted data. A bare workspace
id from a client, or a ``str`` id from a ``RequestContext``, is never accepted.
"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from typing import Literal
from uuid import UUID

from app.workspace import WorkspaceContext

ActorType = Literal["user", "system", "worker"]

# Held only by the three constructors below. Not exported.
_FACTORY_GUARD = object()

DIRECT_CONSTRUCTION_MESSAGE = (
    "AiCallContext must be built with from_workspace, for_worker or system"
)
WORKER_NEEDS_WORKSPACE_MESSAGE = "for_worker requires a workspace_id of type UUID"
BAD_WORKSPACE_CONTEXT_MESSAGE = "from_workspace requires a WorkspaceContext"
BAD_REQUEST_ID_MESSAGE = "request_id must be a non-empty string"


@dataclass(frozen=True)
class AiCallContext:
    workspace_id: UUID | None
    user_id: UUID | None
    actor_type: ActorType
    request_id: str  # correlation id, as in RequestContext
    _factory_guard: InitVar[object | None] = None

    def __post_init__(self, _factory_guard: object | None) -> None:
        if _factory_guard is not _FACTORY_GUARD:
            raise TypeError(DIRECT_CONSTRUCTION_MESSAGE)
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError(BAD_REQUEST_ID_MESSAGE)

    @property
    def is_system(self) -> bool:
        return self.actor_type == "system"

    @classmethod
    def from_workspace(cls, ctx: WorkspaceContext, *, request_id: str) -> AiCallContext:
        """Workspace scope for a user. ``ctx`` must already be verified by the workspace module."""
        if not isinstance(ctx, WorkspaceContext):
            raise TypeError(BAD_WORKSPACE_CONTEXT_MESSAGE)
        return cls(
            workspace_id=ctx.workspace_id,
            user_id=ctx.user_id,
            actor_type="user",
            request_id=request_id,
            _factory_guard=_FACTORY_GUARD,
        )

    @classmethod
    def for_worker(cls, *, workspace_id: UUID, request_id: str) -> AiCallContext:
        """Workspace scope for a worker. The workspace id must come from persisted data."""
        if not isinstance(workspace_id, UUID):
            raise ValueError(WORKER_NEEDS_WORKSPACE_MESSAGE)
        return cls(
            workspace_id=workspace_id,
            user_id=None,
            actor_type="worker",
            request_id=request_id,
            _factory_guard=_FACTORY_GUARD,
        )

    @classmethod
    def system(cls, *, request_id: str) -> AiCallContext:
        """System scope: no workspace, no user. Only ``ai_platform`` and ``rag`` may call this."""
        return cls(
            workspace_id=None,
            user_id=None,
            actor_type="system",
            request_id=request_id,
            _factory_guard=_FACTORY_GUARD,
        )
