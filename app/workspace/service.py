from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthService
from app.core import (
    Conflict,
    Forbidden,
    NotFound,
    SystemClock,
    UUID7Factory,
    get_request_context,
)
from app.events_outbox import publish
from app.observability_audit import AuditRecord, append_audit
from app.workspace.access import WorkspaceContext, WorkspaceRole
from app.workspace.events import (
    InvitationAccepted,
    InvitationCreated,
    MemberAdded,
    MemberRemoved,
    MemberRoleChanged,
    OwnershipTransferred,
    WorkspaceCreated,
    WorkspaceDeleted,
)
from app.workspace.models import Workspace, WorkspaceInvitation, WorkspaceMember


class WorkspaceService:
    @staticmethod
    async def create_workspace_for_owner(
        session: AsyncSession, user_id: UUID, name: str
    ) -> Workspace:
        workspace_id = UUID7Factory(SystemClock()).new()
        slug_base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "workspace"
        workspace = Workspace(
            id=workspace_id,
            name=name.strip(),
            slug=f"{slug_base[:150]}-{workspace_id.hex[:8]}",
        )
        session.add(workspace)
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=WorkspaceRole.OWNER.value,
        )
        session.add(member)
        await session.flush()
        await publish(
            session,
            WorkspaceCreated(
                aggregate_type="workspace", aggregate_id=workspace_id,
                workspace_id=workspace_id,
            ),
        )
        await publish(
            session,
            MemberAdded(
                aggregate_type="workspace", aggregate_id=workspace_id,
                workspace_id=workspace_id, user_id=user_id,
            ),
        )
        await _audit(
            session, actor_id=user_id, workspace_id=workspace_id,
            action="workspace.created", resource_type="workspace", resource_id=str(workspace_id),
        )
        return workspace

    @staticmethod
    async def update_workspace(
        session: AsyncSession, context: WorkspaceContext, *, name: str
    ) -> Workspace:
        workspace = await _locked_workspace(session, context.workspace_id)
        workspace.name = name.strip()
        await _audit(
            session, actor_id=context.user_id, workspace_id=workspace.id,
            action="workspace.updated", resource_type="workspace", resource_id=str(workspace.id),
        )
        return workspace

    @staticmethod
    async def delete_workspace(session: AsyncSession, context: WorkspaceContext) -> None:
        workspace = await _locked_workspace(session, context.workspace_id)
        workspace.deleted_at = SystemClock().now()
        await publish(
            session,
            WorkspaceDeleted(
                aggregate_type="workspace", aggregate_id=workspace.id,
                workspace_id=workspace.id,
            ),
        )
        await _audit(
            session, actor_id=context.user_id, workspace_id=workspace.id,
            action="workspace.deleted", resource_type="workspace", resource_id=str(workspace.id),
        )

    @staticmethod
    async def change_member_role(
        session: AsyncSession,
        context: WorkspaceContext,
        *,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        if role == WorkspaceRole.OWNER:
            raise Conflict("Ownership changes require the ownership-transfer endpoint")
        workspace = await _locked_workspace(session, context.workspace_id)
        target = await _get_member(session, workspace.id, user_id, lock=True)
        old_role = WorkspaceRole(target.role)
        if context.role == WorkspaceRole.ADMIN and old_role != WorkspaceRole.MEMBER:
            raise Forbidden("Administrators cannot change owners or other administrators")
        if old_role == WorkspaceRole.OWNER:
            await _ensure_another_owner(session, workspace.id, user_id)
        target.role = role.value
        await publish(
            session,
            MemberRoleChanged(
                aggregate_type="workspace", aggregate_id=workspace.id,
                workspace_id=workspace.id, user_id=user_id,
            ),
        )
        await _audit(
            session, actor_id=context.user_id, workspace_id=workspace.id,
            action="workspace.member_role_changed", resource_type="workspace_member",
            resource_id=str(target.id),
            details={"old_role": old_role.value, "new_role": role.value},
        )
        return target

    @staticmethod
    async def remove_member(
        session: AsyncSession, context: WorkspaceContext, *, user_id: UUID
    ) -> None:
        workspace = await _locked_workspace(session, context.workspace_id)
        target = await _get_member(session, workspace.id, user_id, lock=True)
        role = WorkspaceRole(target.role)
        if context.role == WorkspaceRole.ADMIN and role != WorkspaceRole.MEMBER:
            raise Forbidden("Administrators cannot remove owners or other administrators")
        if role == WorkspaceRole.OWNER:
            await _ensure_another_owner(session, workspace.id, user_id)
        await session.delete(target)
        await publish(
            session,
            MemberRemoved(
                aggregate_type="workspace", aggregate_id=workspace.id,
                workspace_id=workspace.id, user_id=user_id,
            ),
        )
        await _audit(
            session, actor_id=context.user_id, workspace_id=workspace.id,
            action="workspace.member_removed", resource_type="workspace_member",
            resource_id=str(target.id),
        )

    @staticmethod
    async def transfer_ownership(
        session: AsyncSession, context: WorkspaceContext, *, new_owner_id: UUID
    ) -> None:
        workspace = await _locked_workspace(session, context.workspace_id)
        previous_owner = await _get_member(session, workspace.id, context.user_id, lock=True)
        new_owner = await _get_member(session, workspace.id, new_owner_id, lock=True)
        if previous_owner.role != WorkspaceRole.OWNER.value:
            raise Forbidden("Only an owner can transfer ownership")
        if new_owner.id == previous_owner.id:
            raise Conflict("The new owner must be another workspace member")
        previous_owner.role = WorkspaceRole.ADMIN.value
        new_owner.role = WorkspaceRole.OWNER.value
        await publish(
            session,
            OwnershipTransferred(
                aggregate_type="workspace", aggregate_id=workspace.id,
                workspace_id=workspace.id, previous_owner_id=context.user_id,
                new_owner_id=new_owner_id,
            ),
        )
        await _audit(
            session, actor_id=context.user_id, workspace_id=workspace.id,
            action="workspace.ownership_transferred", resource_type="workspace",
            resource_id=str(workspace.id), details={"new_owner_id": str(new_owner_id)},
        )

    @staticmethod
    async def create_invitation(
        session: AsyncSession,
        context: WorkspaceContext,
        *,
        email: str,
        role: WorkspaceRole,
    ) -> tuple[WorkspaceInvitation, str]:
        if role not in {WorkspaceRole.ADMIN, WorkspaceRole.MEMBER}:
            raise Conflict("Invitations can create administrator or member roles only")
        normalized_email = email.strip().lower()
        invitee = await AuthService.find_user_by_email(normalized_email, session)
        if invitee is not None:
            existing = await session.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == context.workspace_id,
                    WorkspaceMember.user_id == invitee.id,
                )
            )
            if existing is not None:
                raise Conflict("The user is already a workspace member")
        duplicate = await session.scalar(
            select(WorkspaceInvitation.id).where(
                WorkspaceInvitation.workspace_id == context.workspace_id,
                func.lower(WorkspaceInvitation.email) == normalized_email,
                WorkspaceInvitation.status == "pending",
            )
        )
        if duplicate is not None:
            raise Conflict("A pending invitation already exists for this email")
        token = secrets.token_urlsafe(48)
        invitation = WorkspaceInvitation(
            workspace_id=context.workspace_id,
            email=normalized_email,
            role=role.value,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            invited_by_user_id=context.user_id,
            status="pending",
            expires_at=SystemClock().now() + timedelta(days=7),
        )
        session.add(invitation)
        await session.flush()
        await publish(
            session,
            InvitationCreated(
                aggregate_type="workspace", aggregate_id=context.workspace_id,
                workspace_id=context.workspace_id, invitation_id=invitation.id,
            ),
        )
        await _audit(
            session, actor_id=context.user_id, workspace_id=context.workspace_id,
            action="workspace.invitation_created", resource_type="workspace_invitation",
            resource_id=str(invitation.id), details={"role": role.value},
        )
        return invitation, token

    @staticmethod
    async def preview_invitation(
        session: AsyncSession, token: str
    ) -> tuple[Workspace, WorkspaceInvitation]:
        invitation = await _find_invitation(session, token)
        if invitation.status != "pending" or invitation.expires_at <= SystemClock().now():
            raise NotFound("Invitation is unavailable")
        workspace = await session.get(Workspace, invitation.workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise NotFound("Invitation is unavailable")
        return workspace, invitation

    @staticmethod
    async def accept_invitation(
        session: AsyncSession, *, token: str, user_id: UUID
    ) -> WorkspaceMember:
        invitation = await _find_invitation(session, token, lock=True)
        now = SystemClock().now()
        if invitation.status != "pending" or invitation.expires_at <= now:
            raise Conflict("Invitation is expired or unavailable")
        user = await AuthService.get_user(user_id, session)
        if user.email.lower() != invitation.email.lower():
            raise Forbidden("The invitation email does not match the authenticated user")
        duplicate = await session.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == invitation.workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if duplicate is not None:
            raise Conflict("The user is already a workspace member")
        invitation.status = "accepted"
        invitation.accepted_at = now
        member = WorkspaceMember(
            workspace_id=invitation.workspace_id, user_id=user_id, role=invitation.role
        )
        session.add(member)
        await publish(
            session,
            MemberAdded(
                aggregate_type="workspace", aggregate_id=invitation.workspace_id,
                workspace_id=invitation.workspace_id, user_id=user_id,
            ),
        )
        await publish(
            session,
            InvitationAccepted(
                aggregate_type="workspace", aggregate_id=invitation.workspace_id,
                workspace_id=invitation.workspace_id, invitation_id=invitation.id,
                user_id=user_id,
            ),
        )
        await _audit(
            session, actor_id=user_id, workspace_id=invitation.workspace_id,
            action="workspace.invitation_accepted", resource_type="workspace_invitation",
            resource_id=str(invitation.id),
        )
        return member

    @staticmethod
    async def revoke_invitation(
        session: AsyncSession, context: WorkspaceContext, invitation_id: UUID
    ) -> None:
        invitation = await session.scalar(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.workspace_id == context.workspace_id,
                WorkspaceInvitation.id == invitation_id,
                WorkspaceInvitation.status == "pending",
            )
            .with_for_update()
        )
        if invitation is None:
            raise NotFound("Invitation was not found")
        invitation.status = "revoked"
        await _audit(
            session, actor_id=context.user_id, workspace_id=context.workspace_id,
            action="workspace.invitation_revoked", resource_type="workspace_invitation",
            resource_id=str(invitation.id),
        )

    @staticmethod
    async def expire_invitations(
        session: AsyncSession, *, now: datetime | None = None, limit: int = 500
    ) -> int:
        current = now or SystemClock().now()
        rows = list(
            await session.scalars(
                select(WorkspaceInvitation)
                .where(
                    WorkspaceInvitation.status == "pending",
                    WorkspaceInvitation.expires_at <= current,
                )
                .order_by(WorkspaceInvitation.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for invitation in rows:
            invitation.status = "expired"
            await _audit(
                session, actor_id=None, workspace_id=invitation.workspace_id,
                action="workspace.invitation_expired", resource_type="workspace_invitation",
                resource_id=str(invitation.id), actor_type="system",
            )
        return len(rows)


async def _locked_workspace(session: AsyncSession, workspace_id: UUID) -> Workspace:
    workspace = await session.scalar(
        select(Workspace)
        .where(Workspace.id == workspace_id, Workspace.deleted_at.is_(None))
        .with_for_update()
    )
    if workspace is None:
        raise NotFound("Workspace was not found")
    return workspace


async def _get_member(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, *, lock: bool = False
) -> WorkspaceMember:
    statement = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id,
    )
    if lock:
        statement = statement.with_for_update()
    member = await session.scalar(statement)
    if member is None:
        raise NotFound("Workspace member was not found")
    return member


async def _ensure_another_owner(
    session: AsyncSession, workspace_id: UUID, current_owner_id: UUID
) -> None:
    other_owner = await session.scalar(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER.value,
            WorkspaceMember.user_id != current_owner_id,
        )
    )
    if other_owner is None:
        raise Conflict("A workspace must retain at least one owner")


async def _find_invitation(
    session: AsyncSession, token: str, *, lock: bool = False
) -> WorkspaceInvitation:
    digest = hashlib.sha256(token.encode()).hexdigest()
    statement = select(WorkspaceInvitation).where(WorkspaceInvitation.token_hash == digest)
    if lock:
        statement = statement.with_for_update()
    invitation = await session.scalar(statement)
    if invitation is None:
        raise NotFound("Invitation is unavailable")
    return invitation


async def _audit(
    session: AsyncSession,
    *,
    actor_id: UUID | None,
    workspace_id: UUID,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, object] | None = None,
    actor_type: str = "user",
) -> None:
    context = get_request_context()
    await append_audit(
        session,
        AuditRecord(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            request_id=context.request_id if context else "unknown",
            details=details or {},
        ),
    )