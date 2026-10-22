from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from app.events_outbox import DEFAULT_EVENT_REGISTRY, DomainEvent


class WorkspaceCreated(DomainEvent):
    event_type: ClassVar[str] = "workspace.created"
    workspace_id: UUID


class WorkspaceDeleted(DomainEvent):
    event_type: ClassVar[str] = "workspace.deleted"
    workspace_id: UUID


class MemberAdded(DomainEvent):
    event_type: ClassVar[str] = "workspace.member_added"
    workspace_id: UUID
    user_id: UUID


class MemberRoleChanged(DomainEvent):
    event_type: ClassVar[str] = "workspace.member_role_changed"
    workspace_id: UUID
    user_id: UUID


class MemberRemoved(DomainEvent):
    event_type: ClassVar[str] = "workspace.member_removed"
    workspace_id: UUID
    user_id: UUID


class InvitationCreated(DomainEvent):
    event_type: ClassVar[str] = "workspace.invitation_created"
    workspace_id: UUID
    invitation_id: UUID


class InvitationAccepted(DomainEvent):
    event_type: ClassVar[str] = "workspace.invitation_accepted"
    workspace_id: UUID
    invitation_id: UUID
    user_id: UUID


class OwnershipTransferred(DomainEvent):
    event_type: ClassVar[str] = "workspace.ownership_transferred"
    workspace_id: UUID
    previous_owner_id: UUID
    new_owner_id: UUID


for event_model in (
    WorkspaceCreated,
    WorkspaceDeleted,
    MemberAdded,
    MemberRoleChanged,
    MemberRemoved,
    InvitationCreated,
    InvitationAccepted,
    OwnershipTransferred,
):
    DEFAULT_EVENT_REGISTRY.register(event_model)