from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthService, User
from app.core import CursorParams, NotFound, ValidationFailed
from app.db_migrations import database_session
from app.workspace import (
    WorkspaceAccessService,
    WorkspaceContext,
    WorkspacePermission,
    WorkspaceRole,
    WorkspaceService,
    require_workspace_permission,
)
from app.workspace.models import Workspace, WorkspaceInvitation, WorkspaceMember
from app.workspace.schemas import (
    InvitationCreateRequest,
    InvitationListResponse,
    InvitationPreviewResponse,
    InvitationResponse,
    MemberListResponse,
    MemberResponse,
    MemberRoleRequest,
    OwnershipTransferRequest,
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

ReadWorkspace = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.WORKSPACE_READ)),
]
UpdateWorkspace = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.WORKSPACE_UPDATE)),
]
DeleteWorkspace = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.WORKSPACE_DELETE)),
]
ReadMembers = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.MEMBER_READ)),
]
InviteMembers = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.MEMBER_INVITE)),
]
UpdateMemberRole = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.MEMBER_UPDATE_ROLE)),
]
RemoveMember = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.MEMBER_REMOVE)),
]
TransferOwnership = Annotated[
    WorkspaceContext,
    Depends(require_workspace_permission(WorkspacePermission.OWNERSHIP_TRANSFER)),
]


def register_routes(app: FastAPI) -> None:
    @app.get("/api/v1/workspaces", response_model=WorkspaceListResponse, tags=["workspace"])
    async def list_workspaces(
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
        page: Annotated[CursorParams, Depends()],
    ) -> WorkspaceListResponse:
        items = await WorkspaceAccessService.list_workspaces_for_user(session, user.id)
        selected, next_cursor = _paginate(items, page)
        return WorkspaceListResponse(items=selected, next_cursor=next_cursor)

    @app.post("/api/v1/workspaces", response_model=WorkspaceResponse, tags=["workspace"])
    async def create_workspace(
        body: WorkspaceCreateRequest,
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> WorkspaceResponse:
        workspace = await WorkspaceService.create_workspace_for_owner(
            session, user.id, body.name
        )
        return WorkspaceResponse(id=workspace.id, name=workspace.name, slug=workspace.slug)

    @app.get(
        "/api/v1/workspaces/{workspace_id}", response_model=WorkspaceResponse, tags=["workspace"]
    )
    async def get_workspace(
        context: ReadWorkspace,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> WorkspaceResponse:
        workspace = await session.get(Workspace, context.workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise NotFound("Workspace was not found")
        return WorkspaceResponse(id=workspace.id, name=workspace.name, slug=workspace.slug)

    @app.patch(
        "/api/v1/workspaces/{workspace_id}", response_model=WorkspaceResponse, tags=["workspace"]
    )
    async def update_workspace(
        body: WorkspaceUpdateRequest,
        context: UpdateWorkspace,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> WorkspaceResponse:
        workspace = await WorkspaceService.update_workspace(session, context, name=body.name)
        return WorkspaceResponse(id=workspace.id, name=workspace.name, slug=workspace.slug)

    @app.delete("/api/v1/workspaces/{workspace_id}", status_code=204, tags=["workspace"])
    async def delete_workspace(
        context: DeleteWorkspace,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        await WorkspaceService.delete_workspace(session, context)
        return Response(status_code=204)

    @app.get(
        "/api/v1/workspaces/{workspace_id}/members",
        response_model=MemberListResponse,
        tags=["workspace"],
    )
    async def list_members(
        context: ReadMembers,
        session: Annotated[AsyncSession, Depends(database_session)],
        page: Annotated[CursorParams, Depends()],
    ) -> MemberListResponse:
        rows = list(
            await session.scalars(
                select(WorkspaceMember)
                .where(WorkspaceMember.workspace_id == context.workspace_id)
                .order_by(WorkspaceMember.user_id)
            )
        )
        items = [
            MemberResponse(
                user_id=row.user_id, role=WorkspaceRole(row.role), created_at=row.created_at
            )
            for row in rows
        ]
        selected, next_cursor = _paginate(items, page, id_field="user_id")
        return MemberListResponse(items=selected, next_cursor=next_cursor)

    @app.patch(
        "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        response_model=MemberResponse,
        tags=["workspace"],
    )
    async def change_member_role(
        user_id: UUID,
        body: MemberRoleRequest,
        context: UpdateMemberRole,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> MemberResponse:
        member = await WorkspaceService.change_member_role(
            session, context, user_id=user_id, role=body.role
        )
        return MemberResponse(
            user_id=member.user_id,
            role=WorkspaceRole(member.role),
            created_at=member.created_at,
        )

    @app.delete(
        "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        status_code=204,
        tags=["workspace"],
    )
    async def remove_member(
        user_id: UUID,
        context: RemoveMember,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        await WorkspaceService.remove_member(session, context, user_id=user_id)
        return Response(status_code=204)

    @app.post(
        "/api/v1/workspaces/{workspace_id}/ownership-transfer",
        status_code=204,
        tags=["workspace"],
    )
    async def transfer_ownership(
        body: OwnershipTransferRequest,
        context: TransferOwnership,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        await WorkspaceService.transfer_ownership(
            session, context, new_owner_id=body.new_owner_id
        )
        return Response(status_code=204)

    @app.get(
        "/api/v1/workspaces/{workspace_id}/invitations",
        response_model=InvitationListResponse,
        tags=["workspace"],
    )
    async def list_invitations(
        context: InviteMembers,
        session: Annotated[AsyncSession, Depends(database_session)],
        page: Annotated[CursorParams, Depends()],
    ) -> InvitationListResponse:
        invitations = list(
            await session.scalars(
                select(WorkspaceInvitation)
                .where(WorkspaceInvitation.workspace_id == context.workspace_id)
                .order_by(WorkspaceInvitation.id)
            )
        )
        items = [
            InvitationResponse(
                id=item.id,
                email=item.email,
                role=WorkspaceRole(item.role),
                status=item.status,
                expires_at=item.expires_at,
                created_at=item.created_at,
            )
            for item in invitations
        ]
        selected, next_cursor = _paginate(items, page)
        return InvitationListResponse(
            items=selected,
            next_cursor=next_cursor,
        )

    @app.post(
        "/api/v1/workspaces/{workspace_id}/invitations",
        response_model=InvitationResponse,
        tags=["workspace"],
    )
    async def create_invitation(
        body: InvitationCreateRequest,
        context: InviteMembers,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> InvitationResponse:
        invitation, token = await WorkspaceService.create_invitation(
            session, context, email=body.email, role=body.role
        )
        return InvitationResponse(
            id=invitation.id,
            email=invitation.email,
            role=WorkspaceRole(invitation.role),
            status=invitation.status,
            expires_at=invitation.expires_at,
            created_at=invitation.created_at,
            token=token,
        )

    @app.delete(
        "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        status_code=204,
        tags=["workspace"],
    )
    async def revoke_invitation(
        invitation_id: UUID,
        context: InviteMembers,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        await WorkspaceService.revoke_invitation(session, context, invitation_id)
        return Response(status_code=204)

    @app.get(
        "/api/v1/invitations/{token}",
        response_model=InvitationPreviewResponse,
        tags=["workspace"],
    )
    async def preview_invitation(
        token: str,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> InvitationPreviewResponse:
        workspace, invitation = await WorkspaceService.preview_invitation(session, token)
        return InvitationPreviewResponse(
            workspace_name=workspace.name,
            role=WorkspaceRole(invitation.role),
            expires_at=invitation.expires_at,
        )

    @app.post(
        "/api/v1/invitations/{token}/accept",
        response_model=MemberResponse,
        tags=["workspace"],
    )
    async def accept_invitation(
        token: str,
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> MemberResponse:
        member = await WorkspaceService.accept_invitation(session, token=token, user_id=user.id)
        return MemberResponse(
            user_id=member.user_id,
            role=WorkspaceRole(member.role),
            created_at=member.created_at,
        )


def _paginate[T](
    items: list[T], params: CursorParams, *, id_field: str = "id"
) -> tuple[list[T], str | None]:
    start = 0
    if params.cursor:
        try:
            cursor_id = UUID(params.cursor)
        except ValueError as error:
            raise ValidationFailed("Cursor is invalid") from error
        for index, item in enumerate(items):
            if getattr(item, id_field) == cursor_id:
                start = index + 1
                break
        else:
            raise ValidationFailed("Cursor is invalid")
    selected = items[start : start + params.limit + 1]
    has_more = len(selected) > params.limit
    page_items = selected[: params.limit]
    next_cursor = str(getattr(page_items[-1], id_field)) if has_more and page_items else None
    return page_items, next_cursor