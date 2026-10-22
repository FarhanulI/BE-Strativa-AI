from app.workspace.access import ROLE_PERMISSIONS, WorkspacePermission, WorkspaceRole


def test_owner_has_every_workspace_permission() -> None:
    assert ROLE_PERMISSIONS[WorkspaceRole.OWNER] == frozenset(WorkspacePermission)


def test_admin_cannot_delete_workspace_transfer_or_manage_admins() -> None:
    assert ROLE_PERMISSIONS[WorkspaceRole.ADMIN] == frozenset(
        permission
        for permission in WorkspacePermission
        if permission
        not in {
            WorkspacePermission.WORKSPACE_DELETE,
            WorkspacePermission.OWNERSHIP_TRANSFER,
        }
    )


def test_member_can_only_read_workspace_and_member_list() -> None:
    assert ROLE_PERMISSIONS[WorkspaceRole.MEMBER] == frozenset(
        {
            WorkspacePermission.WORKSPACE_READ,
            WorkspacePermission.MEMBER_READ,
            WorkspacePermission.PROFILE_READ,
            WorkspacePermission.PROFILE_UPDATE,
        }
    )


def test_profile_permission_matrix() -> None:
    profile_permissions = {
        WorkspacePermission.PROFILE_READ,
        WorkspacePermission.PROFILE_CREATE,
        WorkspacePermission.PROFILE_UPDATE,
        WorkspacePermission.PROFILE_ARCHIVE,
    }

    assert profile_permissions <= ROLE_PERMISSIONS[WorkspaceRole.OWNER]
    assert profile_permissions <= ROLE_PERMISSIONS[WorkspaceRole.ADMIN]
    assert ROLE_PERMISSIONS[WorkspaceRole.MEMBER] & profile_permissions == {
        WorkspacePermission.PROFILE_READ,
        WorkspacePermission.PROFILE_UPDATE,
    }