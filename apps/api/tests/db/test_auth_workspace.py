from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_contract import create_app
from app.auth import AuthService, AuthSession, User, UserRegistered
from app.auth.security import decode_access_token, hash_password
from app.auth.service import create_auth_session
from app.core import Conflict, Forbidden, NotFound, Settings, SystemClock, UUID7Factory
from app.db_migrations import async_session_factory, build_async_engine, database_session
from app.events_outbox import OutboxEvent, publish
from app.observability_audit import AuditLog
from app.workspace import (
    ROLE_PERMISSIONS,
    WorkspaceContext,
    WorkspacePermission,
    WorkspaceRole,
    WorkspaceService,
)
from app.workspace.models import Workspace, WorkspaceMember
from tests.helpers.tenant_isolation import (
    WORKSPACE_SCOPED_ROUTES,
    assert_nonmember_routes_hidden,
)

pytestmark = pytest.mark.db


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


def _user(email: str) -> User:
    return User(
        id=_new_id(),
        email=email,
        password_hash="$argon2id$test-only",
        display_name=email.split("@", maxsplit=1)[0],
        is_active=True,
    )


async def _seed_workspace(
    session: AsyncSession, owner: User, *, name: str = "Test workspace"
) -> Workspace:
    session.add(owner)
    await session.flush()
    return await WorkspaceService.create_workspace_for_owner(session, owner.id, name)


def _override_session_with_savepoint(session: AsyncSession):
    async def request_session() -> AsyncIterator[AsyncSession]:
        savepoint = await session.begin_nested()
        try:
            yield session
        except BaseException:
            if savepoint.is_active:
                await savepoint.rollback()
            raise
        else:
            if savepoint.is_active:
                await savepoint.commit()

    return request_session


@pytest.mark.asyncio
async def test_register_endpoint_creates_user_workspace_owner_and_safe_events(
    db_session: AsyncSession,
) -> None:
    app = create_app(
        Settings(_env_file=None, auth_jwt_secret="test-secret-long-enough-for-hs256-signing")
    )
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "Register@Example.test",
                "password": "correct horse battery staple",
                "display_name": "Register User",
                "workspace_name": "Register Workspace",
            },
        )

    assert response.status_code == 200
    result = response.json()
    user_id = UUID(result["user"]["id"])
    workspace_id = UUID(result["workspace"]["id"])
    assert result["user"]["email"] == "register@example.test"
    assert result["workspace"]["role"] == "OWNER"
    assert result["access_token"]
    assert result["expires_in"] == 900
    assert (await db_session.get(User, user_id)).password_hash.startswith("$argon2id$")
    assert await db_session.scalar(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.role == WorkspaceRole.OWNER.value,
        )
    ) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id)
    ) == 1
    events = list(
        await db_session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id.in_([user_id, workspace_id])
            )
        )
    )
    assert {event.event_type for event in events} == {
        "auth.user_registered",
        "workspace.created",
        "workspace.member_added",
    }
    assert all("password" not in str(event.payload).lower() for event in events)
    assert all("token" not in str(event.payload).lower() for event in events)
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("refresh_token=")
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert "path=/api/v1/auth" in cookie
    assert "max-age=2592000" in cookie


@pytest.mark.asyncio
async def test_auth_me_patch_updates_display_name_audits_and_returns_workspace_roles(
    db_session: AsyncSession,
) -> None:
    user = _user("me-patch@example.test")
    workspace = await _seed_workspace(db_session, user, name="Me patch workspace")
    workspace_id = workspace.id
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: user
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/api/v1/auth/me",
            json={"display_name": "  Updated creator  "},
        )
        invalid = await client.patch(
            "/api/v1/auth/me",
            json={"display_name": "   "},
        )

    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "Updated creator"
    assert response.json()["workspaces"] == [
        {
            "id": str(workspace_id),
            "name": "Me patch workspace",
            "slug": response.json()["workspaces"][0]["slug"],
            "role": "OWNER",
        }
    ]
    assert invalid.status_code == 422
    assert any(
        error["field"] == "display_name" for error in invalid.json()["field_errors"]
    )
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_id == user.id,
            AuditLog.action == "auth.display_name_updated",
        )
    ) == 1


@pytest.mark.asyncio
async def test_register_endpoint_failure_leaves_no_partial_rows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings(_env_file=None, auth_jwt_secret="test-secret-long-enough-for-hs256-signing")
    )
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)

    async def fail_workspace_creation(
        session: AsyncSession, user_id: UUID, name: str
    ) -> Workspace:
        raise RuntimeError("workspace failure")

    monkeypatch.setattr(WorkspaceService, "create_workspace_for_owner", fail_workspace_creation)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        with pytest.raises(RuntimeError, match="workspace failure"):
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "failure@example.test",
                    "password": "correct horse battery staple",
                    "display_name": "Failure User",
                    "workspace_name": "Failure Workspace",
                },
            )

    assert await AuthService.find_user_by_email("failure@example.test", db_session) is None
    assert await db_session.scalar(
        select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.event_type == "auth.user_registered"
        )
    ) == 0


@pytest.mark.asyncio
async def test_auth_me_patch_updates_display_name_and_audits(db_session: AsyncSession) -> None:
    user = _user("me-patch@example.test")
    workspace = await _seed_workspace(db_session, user, name="Me patch workspace")
    workspace_id = workspace.id
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: user
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            "/api/v1/auth/me", json={"display_name": "  Updated creator  "}
        )
        invalid = await client.patch("/api/v1/auth/me", json={"display_name": "   "})

    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "Updated creator"
    assert response.json()["workspaces"][0]["id"] == str(workspace_id)
    assert response.json()["workspaces"][0]["role"] == "OWNER"
    assert invalid.status_code == 422
    assert any(
        error["field"] == "display_name" for error in invalid.json()["field_errors"]
    )
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.actor_id == user.id,
            AuditLog.action == "auth.display_name_updated",
        )
    ) == 1


@pytest.mark.asyncio
async def test_login_logout_all_audit_and_secret_redaction(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    password = "login test secret password"
    user = User(
        id=_new_id(),
        email="login-audit@example.test",
        password_hash=hash_password(password),
        display_name="Login audit",
        is_active=True,
    )
    password_hash = user.password_hash
    db_session.add(user)
    await db_session.flush()

    class FakeRedis:
        async def eval(self, *arguments: object) -> int:
            return 1

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr(Redis, "from_url", lambda *args, **kwargs: FakeRedis())
    settings = Settings(
        _env_file=None,
        redis_url="redis://localhost/1",
        auth_jwt_secret="test-secret-long-enough-for-hs256-signing",
    )
    app = create_app(settings)
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": password},
        )
        assert login.status_code == 200
        access_token = login.json()["access_token"]
        assert login.json()["expires_in"] == 900
        refresh_token = login.cookies.get("refresh_token")
        assert refresh_token

        bad_password = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "wrong password"},
        )
        unknown_email = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.test", "password": "wrong password"},
        )
        assert bad_password.status_code == unknown_email.status_code == 401
        assert bad_password.json()["detail"] == unknown_email.json()["detail"]

        logout_all = await client.post(
            "/api/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert logout_all.status_code == 204

    assert password not in caplog.text
    assert password_hash not in caplog.text
    assert access_token not in caplog.text
    assert refresh_token not in caplog.text
    audits = list(
        await db_session.scalars(
            select(AuditLog).where(
                AuditLog.action.in_(
                    {
                        "auth.login_success",
                        "auth.login_failure",
                        "auth.logout_all",
                    }
                )
            )
        )
    )
    assert {entry.action for entry in audits} == {
        "auth.login_success",
        "auth.login_failure",
        "auth.logout_all",
    }
    assert sum(entry.action == "auth.login_failure" for entry in audits) == 2
    assert all(
        password not in json.dumps(entry.details)
        and password_hash not in json.dumps(entry.details)
        and refresh_token not in json.dumps(entry.details)
        and access_token not in json.dumps(entry.details)
        for entry in audits
    )
    auth_sessions = list(
        await db_session.scalars(
            select(AuthSession).where(AuthSession.user_id == user.id)
        )
    )
    assert auth_sessions and all(row.revoked_at is not None for row in auth_sessions)


@pytest.mark.asyncio
async def test_refresh_rotates_and_replay_revokes_the_entire_family(
    migrated_test_schema: Settings,
) -> None:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True), pooled=False
    )
    factory = async_session_factory(engine)
    settings = Settings(
        _env_file=None,
        auth_jwt_secret="test-secret-long-enough-for-hs256-signing",
    )
    user = _user("refresh@example.test")
    try:
        async with factory() as session, session.begin():
            session.add(user)
            await session.flush()
            original_session, original_token = await create_auth_session(
                session,
                user_id=user.id,
                now=SystemClock().now(),
                user_agent="test-agent",
                ip="192.0.2.10",
            )
            original_session_id = original_session.id
            family_id = original_session.family_id

        app = create_app(settings)

        async def request_session() -> AsyncIterator[AsyncSession]:
            async with factory() as session:
                try:
                    yield session
                except BaseException:
                    await session.rollback()
                    raise
                else:
                    if session.in_transaction():
                        await session.commit()

        app.dependency_overrides[database_session] = request_session

        async def send_refresh() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://test"
            ) as client:
                return await client.post(
                    "/api/v1/auth/refresh",
                    headers={"Cookie": f"refresh_token={original_token}"},
                )

        first, second = await asyncio.gather(send_refresh(), send_refresh())
        responses_by_status = {first.status_code: first, second.status_code: second}
        assert set(responses_by_status) == {200, 401}
        rotated = responses_by_status[200]
        replay = responses_by_status[401]
        assert rotated.json()["expires_in"] == 900
        successor_token = rotated.cookies.get("refresh_token")
        assert successor_token and successor_token != original_token
        claims = decode_access_token(settings, rotated.json()["access_token"])
        assert claims[0] == user.id
        assert replay.json()["code"] == "unauthenticated"

        async with factory() as session:
            sessions = list(
                await session.scalars(
                    select(AuthSession).where(AuthSession.family_id == family_id)
                )
            )
            assert len(sessions) == 2
            assert all(item.revoked_at is not None for item in sessions)
            assert sessions[0].id == original_session_id
            assert await session.scalar(
                select(func.count()).select_from(AuditLog).where(
                    AuditLog.action == "auth.refresh_reuse_detected",
                    AuditLog.actor_id == user.id,
                )
            ) == 1
    finally:
        async with factory() as session, session.begin():
            await session.execute(User.__table__.delete().where(User.id == user.id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_registration_state_and_events_roll_back_atomically(db_session: AsyncSession) -> None:
    user = _user("rollback@example.test")
    savepoint = await db_session.begin_nested()
    db_session.add(user)
    await db_session.flush()
    workspace = await WorkspaceService.create_workspace_for_owner(
        db_session, user.id, "Rollback workspace"
    )
    await publish(
        db_session,
        UserRegistered(aggregate_type="user", aggregate_id=user.id, user_id=user.id),
    )
    user_id, workspace_id = user.id, workspace.id
    await savepoint.rollback()

    assert await db_session.get(User, user_id) is None
    assert await db_session.get(Workspace, workspace_id) is None
    assert await db_session.scalar(
        select(func.count()).select_from(OutboxEvent).where(
            OutboxEvent.aggregate_id.in_([user_id, workspace_id])
        )
    ) == 0
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.workspace_id == workspace_id)
    ) == 0


@pytest.mark.asyncio
async def test_nonmember_gets_404_for_every_registered_workspace_route(
    db_session: AsyncSession,
) -> None:
    owner = _user("owner@example.test")
    nonmember = _user("outsider@example.test")
    workspace = await _seed_workspace(db_session, owner)
    db_session.add(nonmember)
    await db_session.flush()
    app = create_app(Settings(_env_file=None))

    async def current_user() -> User:
        return nonmember

    async def request_session():
        yield db_session

    app.dependency_overrides[AuthService.get_current_user] = current_user
    from app.db_migrations import database_session

    app.dependency_overrides[database_session] = request_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await assert_nonmember_routes_hidden(client, workspace_id=workspace.id)


@pytest.mark.asyncio
async def test_role_matrix_is_enforced_on_every_workspace_scoped_endpoint(
    db_session: AsyncSession,
) -> None:
    owner = _user("matrix-owner@example.test")
    admin = _user("matrix-admin@example.test")
    member = _user("matrix-member@example.test")
    workspace = await _seed_workspace(db_session, owner, name="Matrix workspace")
    db_session.add_all([admin, member])
    await db_session.flush()
    owner_id, admin_id, member_id, workspace_id = (
        owner.id,
        admin.id,
        member.id,
        workspace.id,
    )
    db_session.add_all(
        [
            WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="ADMIN"),
            WorkspaceMember(workspace_id=workspace.id, user_id=member.id, role="MEMBER"),
        ]
    )
    await db_session.flush()
    owner_context = WorkspaceContext(
        user_id=owner_id, workspace_id=workspace_id, role=WorkspaceRole.OWNER
    )
    invitation, _ = await WorkspaceService.create_invitation(
        db_session,
        owner_context,
        email="matrix-pending@example.test",
        role=WorkspaceRole.MEMBER,
    )
    invitation_id = invitation.id
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    current_actor = User(
        id=owner_id,
        email=owner.email,
        password_hash=owner.password_hash,
        display_name=owner.display_name,
        is_active=True,
    )

    async def current_user() -> User:
        return current_actor

    app.dependency_overrides[AuthService.get_current_user] = current_user
    permission_by_route = {
        ("GET", "/api/v1/workspaces/{workspace_id}"): WorkspacePermission.WORKSPACE_READ,
        ("PATCH", "/api/v1/workspaces/{workspace_id}"): WorkspacePermission.WORKSPACE_UPDATE,
        ("DELETE", "/api/v1/workspaces/{workspace_id}"): WorkspacePermission.WORKSPACE_DELETE,
        (
            "GET",
            "/api/v1/workspaces/{workspace_id}/members",
        ): WorkspacePermission.MEMBER_READ,
        (
            "PATCH",
            "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        ): WorkspacePermission.MEMBER_UPDATE_ROLE,
        (
            "DELETE",
            "/api/v1/workspaces/{workspace_id}/members/{user_id}",
        ): WorkspacePermission.MEMBER_REMOVE,
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/ownership-transfer",
        ): WorkspacePermission.OWNERSHIP_TRANSFER,
        (
            "GET",
            "/api/v1/workspaces/{workspace_id}/invitations",
        ): WorkspacePermission.MEMBER_INVITE,
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/invitations",
        ): WorkspacePermission.MEMBER_INVITE,
        (
            "DELETE",
            "/api/v1/workspaces/{workspace_id}/invitations/{invitation_id}",
        ): WorkspacePermission.MEMBER_INVITE,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for role, actor in (
            (
                WorkspaceRole.OWNER,
                User(
                    id=owner_id, email="matrix-owner@example.test",
                    password_hash="$argon2id$test-only", display_name="Owner", is_active=True,
                ),
            ),
            (
                WorkspaceRole.ADMIN,
                User(
                    id=admin_id, email="matrix-admin@example.test",
                    password_hash="$argon2id$test-only", display_name="Admin", is_active=True,
                ),
            ),
            (
                WorkspaceRole.MEMBER,
                User(
                    id=member_id, email="matrix-member@example.test",
                    password_hash="$argon2id$test-only", display_name="Member", is_active=True,
                ),
            ),
        ):
            current_actor = actor
            for route in WORKSPACE_SCOPED_ROUTES:
                permission = permission_by_route[(route.method, route.path)]
                allowed = permission in ROLE_PERMISSIONS[role]
                path = route.path.format(
                    workspace_id=workspace_id,
                    user_id=member_id,
                    invitation_id=invitation_id,
                )
                body = route.body
                if route.path.endswith("ownership-transfer"):
                    body = {"new_owner_id": str(member_id)}
                savepoint = await db_session.begin_nested()
                try:
                    response = await client.request(route.method, path, json=body)
                    expected_status = (
                        403
                        if not allowed
                        else 204
                        if route.method == "DELETE" or route.path.endswith("ownership-transfer")
                        else 200
                    )
                    assert response.status_code == expected_status, (
                        f"{role} {route.method} {route.path}: {response.status_code}"
                    )
                finally:
                    await savepoint.rollback()


@pytest.mark.asyncio
async def test_admin_cannot_change_or_remove_owners_or_other_admins(
    db_session: AsyncSession,
) -> None:
    owner = _user("protected-owner@example.test")
    admin = _user("operator-admin@example.test")
    peer_admin = _user("protected-admin@example.test")
    workspace = await _seed_workspace(db_session, owner, name="Protected roles")
    db_session.add_all([admin, peer_admin])
    await db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(workspace_id=workspace.id, user_id=admin.id, role="ADMIN"),
            WorkspaceMember(workspace_id=workspace.id, user_id=peer_admin.id, role="ADMIN"),
        ]
    )
    await db_session.flush()
    admin_context = WorkspaceContext(
        user_id=admin.id, workspace_id=workspace.id, role=WorkspaceRole.ADMIN
    )

    for protected_user_id in (owner.id, peer_admin.id):
        with pytest.raises(Forbidden):
            await WorkspaceService.change_member_role(
                db_session,
                admin_context,
                user_id=protected_user_id,
                role=WorkspaceRole.MEMBER,
            )
        with pytest.raises(Forbidden):
            await WorkspaceService.remove_member(
                db_session, admin_context, user_id=protected_user_id
            )


@pytest.mark.asyncio
async def test_invitation_create_preview_accept_and_rejection_paths(
    db_session: AsyncSession,
) -> None:
    owner = _user("owner-invite@example.test")
    invitee = _user("invitee@example.test")
    wrong_user = _user("different@example.test")
    workspace = await _seed_workspace(db_session, owner, name="Invite workspace")
    db_session.add_all([invitee, wrong_user])
    await db_session.flush()
    context = WorkspaceContext(
        user_id=owner.id, workspace_id=workspace.id, role=WorkspaceRole.OWNER
    )

    invitation, token = await WorkspaceService.create_invitation(
        db_session,
        context,
        email=invitee.email,
        role=WorkspaceRole.MEMBER,
    )
    preview_workspace, preview = await WorkspaceService.preview_invitation(db_session, token)
    assert preview_workspace.name == workspace.name
    assert preview.id == invitation.id
    with pytest.raises(Forbidden):
        await WorkspaceService.accept_invitation(
            db_session, token=token, user_id=wrong_user.id
        )

    member = await WorkspaceService.accept_invitation(
        db_session, token=token, user_id=invitee.id
    )
    assert member.role == WorkspaceRole.MEMBER.value
    with pytest.raises(Conflict):
        await WorkspaceService.accept_invitation(db_session, token=token, user_id=invitee.id)

    revoked, revoked_token = await WorkspaceService.create_invitation(
        db_session,
        context,
        email="revoked@example.test",
        role=WorkspaceRole.ADMIN,
    )
    await WorkspaceService.revoke_invitation(db_session, context, revoked.id)
    with pytest.raises(Conflict):
        await WorkspaceService.accept_invitation(
            db_session, token=revoked_token, user_id=wrong_user.id
        )

    expired, expired_token = await WorkspaceService.create_invitation(
        db_session,
        context,
        email="expired@example.test",
        role=WorkspaceRole.MEMBER,
    )
    expired.expires_at = SystemClock().now() - timedelta(seconds=1)
    with pytest.raises(NotFound):
        await WorkspaceService.preview_invitation(db_session, expired_token)
    with pytest.raises(Conflict):
        await WorkspaceService.accept_invitation(
            db_session, token=expired_token, user_id=wrong_user.id
        )


@pytest.mark.asyncio
async def test_invitation_expiration_job_is_idempotent(db_session: AsyncSession) -> None:
    owner = _user("owner-expire@example.test")
    workspace = await _seed_workspace(db_session, owner, name="Expire workspace")
    context = WorkspaceContext(
        user_id=owner.id, workspace_id=workspace.id, role=WorkspaceRole.OWNER
    )
    invitation, _ = await WorkspaceService.create_invitation(
        db_session,
        context,
        email="stale-invitation@example.test",
        role=WorkspaceRole.MEMBER,
    )
    now = invitation.expires_at + timedelta(seconds=1)

    assert await WorkspaceService.expire_invitations(db_session, now=now) == 1
    assert invitation.status == "expired"
    assert await WorkspaceService.expire_invitations(db_session, now=now) == 0


@pytest.mark.asyncio
async def test_concurrent_owner_removals_preserve_one_owner(migrated_test_schema: Settings) -> None:
    engine = build_async_engine(
        migrated_test_schema.require_database_url(direct=True), pooled=False
    )
    factory = async_session_factory(engine)
    owner_ids = [_new_id(), _new_id()]
    workspace_id = _new_id()
    try:
        async with factory() as session, session.begin():
            for index, owner_id in enumerate(owner_ids):
                session.add(
                    User(
                        id=owner_id,
                        email=f"concurrent-{owner_id.hex}@example.test",
                        password_hash="$argon2id$test-only",
                        display_name=f"Owner {index}",
                        is_active=True,
                    )
                )
            session.add(
                Workspace(
                    id=workspace_id,
                    name="Concurrent owners",
                    slug=f"concurrent-{workspace_id.hex[:12]}",
                )
            )
            session.add_all(
                [
                    WorkspaceMember(
                        id=_new_id(),
                        workspace_id=workspace_id,
                        user_id=owner_id,
                        role=WorkspaceRole.OWNER.value,
                    )
                    for owner_id in owner_ids
                ]
            )

        async def remove_own_membership(owner_id: UUID) -> str:
            try:
                async with factory() as session, session.begin():
                    context = WorkspaceContext(
                        user_id=owner_id,
                        workspace_id=workspace_id,
                        role=WorkspaceRole.OWNER,
                    )
                    await WorkspaceService.remove_member(
                        session, context, user_id=owner_id
                    )
                return "removed"
            except Conflict:
                return "rejected"

        outcomes = await asyncio.gather(
            *(remove_own_membership(owner_id) for owner_id in owner_ids)
        )
        assert sorted(outcomes) == ["rejected", "removed"]
        async with factory() as session:
            remaining = await session.scalar(
                select(func.count()).select_from(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceRole.OWNER.value,
                )
            )
            assert remaining == 1
    finally:
        async with factory() as session, session.begin():
            await session.execute(
                Workspace.__table__.delete().where(Workspace.id == workspace_id)
            )
            await session.execute(User.__table__.delete().where(User.id.in_(owner_ids)))
        await engine.dispose()