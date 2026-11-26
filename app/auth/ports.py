"""What auth needs from workspaces, as protocols (T-016 step 2, ADR-0003).

``auth`` owns these protocols and imports nothing from ``app.workspace``. The composition root
(``app.api_contract.create_app``) passes the workspace implementations in when it registers the
auth routes. Both methods take the caller's ``AsyncSession``, so registration still creates the
user, workspace, OWNER membership and events in one transaction (AUTH-AC-2), and ``/me`` still
reads roles through the workspace public interface (AUTH-AC-7, AUTH-INV-7).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


class RoleName(Protocol):
    @property
    def value(self) -> str: ...


class WorkspaceReference(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def slug(self) -> str: ...


class WorkspaceMembership(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def slug(self) -> str: ...

    @property
    def role(self) -> RoleName: ...


class WorkspaceProvisioner(Protocol):
    """Creates the initial workspace and OWNER membership inside the caller's transaction."""

    async def create_workspace_for_owner(
        self, session: AsyncSession, user_id: UUID, name: str
    ) -> WorkspaceReference: ...


class WorkspaceRoleReader(Protocol):
    """Lists a user's workspaces and roles; the caller owns the session."""

    async def list_workspaces_for_user(
        self, session: AsyncSession, user_id: UUID
    ) -> Sequence[WorkspaceMembership]: ...
