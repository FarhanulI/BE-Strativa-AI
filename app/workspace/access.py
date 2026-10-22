from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthService, User
from app.core import Forbidden, NotFound
from app.db_migrations import database_session
from app.workspace.models import Workspace, WorkspaceMember


class WorkspaceRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspacePermission(StrEnum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    MEMBER_READ = "member:read"
    MEMBER_INVITE = "member:invite"
    MEMBER_UPDATE_ROLE = "member:update_role"
    MEMBER_REMOVE = "member:remove"
    OWNERSHIP_TRANSFER = "ownership:transfer"
    PROFILE_READ = "profile:read"
    PROFILE_CREATE = "profile:create"
    PROFILE_UPDATE = "profile:update"
    PROFILE_ARCHIVE = "profile:archive"


class WorkspaceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole


class WorkspaceSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    role: WorkspaceRole


# New module permissions belong here; route handlers continue to use the shared dependency.
ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[WorkspacePermission]] = {
    WorkspaceRole.OWNER: frozenset(WorkspacePermission),
    WorkspaceRole.ADMIN: frozenset(
        permission
        for permission in WorkspacePermission
        if permission
        not in {
            WorkspacePermission.WORKSPACE_DELETE,
            WorkspacePermission.OWNERSHIP_TRANSFER,
        }
    ),
    WorkspaceRole.MEMBER: frozenset(
        {
            WorkspacePermission.WORKSPACE_READ,
            WorkspacePermission.MEMBER_READ,
            WorkspacePermission.PROFILE_READ,
            WorkspacePermission.PROFILE_UPDATE,
        }
    ),
}


class WorkspaceAccessService:
    @staticmethod
    async def authorize(
        session: AsyncSession,
        *,
        user_id: UUID,
        workspace_id: UUID,
        permission: WorkspacePermission,
    ) -> WorkspaceContext:
        result = await session.execute(
            select(WorkspaceMember.role)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
                Workspace.deleted_at.is_(None),
            )
        )
        role_value = result.scalar_one_or_none()
        if role_value is None:
            raise NotFound("Workspace was not found")
        role = WorkspaceRole(role_value)
        if permission not in ROLE_PERMISSIONS[role]:
            raise Forbidden("You do not have permission to perform this action")
        return WorkspaceContext(user_id=user_id, workspace_id=workspace_id, role=role)

    @staticmethod
    async def is_member(session: AsyncSession, *, user_id: UUID, workspace_id: UUID) -> bool:
        result = await session.execute(
            select(WorkspaceMember.id)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id == workspace_id,
                Workspace.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_workspaces_for_user(
        session: AsyncSession, user_id: UUID
    ) -> list[WorkspaceSummary]:
        rows = await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.id)
        )
        return [
            WorkspaceSummary(id=row.id, name=row.name, slug=row.slug, role=WorkspaceRole(role))
            for row, role in rows
        ]


def require_workspace_permission(permission: WorkspacePermission | str):
    required = WorkspacePermission(permission)

    async def dependency(
        workspace_id: UUID,
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> WorkspaceContext:
        return await WorkspaceAccessService.authorize(
            session,
            user_id=user.id,
            workspace_id=workspace_id,
            permission=required,
        )

    return dependency