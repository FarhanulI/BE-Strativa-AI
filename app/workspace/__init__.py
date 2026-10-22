from app.workspace.access import (
    ROLE_PERMISSIONS,
    WorkspaceAccessService,
    WorkspaceContext,
    WorkspacePermission,
    WorkspaceRole,
    WorkspaceSummary,
    require_workspace_permission,
)
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
from app.workspace.jobs import register_jobs
from app.workspace.models import Workspace, WorkspaceInvitation, WorkspaceMember
from app.workspace.service import WorkspaceService


def register_routes(app) -> None:
    from app.workspace.routes import register_routes as register

    register(app)


__all__ = [
    "InvitationAccepted",
    "InvitationCreated",
    "MemberAdded",
    "MemberRemoved",
    "MemberRoleChanged",
    "OwnershipTransferred",
    "ROLE_PERMISSIONS",
    "Workspace",
    "WorkspaceAccessService",
    "WorkspaceContext",
    "WorkspaceCreated",
    "WorkspaceDeleted",
    "WorkspaceInvitation",
    "WorkspaceMember",
    "WorkspacePermission",
    "WorkspaceRole",
    "WorkspaceService",
    "WorkspaceSummary",
    "require_workspace_permission",
    "register_jobs",
    "register_routes",
]