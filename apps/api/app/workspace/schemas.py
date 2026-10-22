from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core import CursorPage
from app.workspace.access import WorkspaceRole, WorkspaceSummary


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str


class WorkspaceListResponse(CursorPage[WorkspaceSummary]):
    pass


class MemberRoleRequest(BaseModel):
    role: WorkspaceRole


class OwnershipTransferRequest(BaseModel):
    new_owner_id: UUID


class MemberResponse(BaseModel):
    user_id: UUID
    role: WorkspaceRole
    created_at: datetime


class MemberListResponse(CursorPage[MemberResponse]):
    pass


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: WorkspaceRole


class InvitationResponse(BaseModel):
    id: UUID
    email: str
    role: WorkspaceRole
    status: str
    expires_at: datetime
    created_at: datetime
    token: str | None = None


class InvitationPreviewResponse(BaseModel):
    workspace_name: str
    role: WorkspaceRole
    expires_at: datetime


class InvitationListResponse(CursorPage[InvitationResponse]):
    pass