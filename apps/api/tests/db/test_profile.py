from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_contract import create_app
from app.auth import AuthService, User
from app.core import NotFound, Settings, SystemClock, UUID7Factory
from app.db_migrations import database_session
from app.events_outbox import OutboxEvent, ProcessedEvent
from app.observability_audit import AuditLog
from app.profile import ProfileService
from app.profile.models import ContentProfile, ProfileProduct
from app.profile.schemas import (
    ProfileCreateRequest,
    ProfileItemCreateRequest,
    ProfileItemType,
    ProfilePatchRequest,
    ProfileType,
)
from app.workspace import (
    ROLE_PERMISSIONS,
    WorkspaceContext,
    WorkspacePermission,
    WorkspaceRole,
    WorkspaceService,
)
from app.workspace.models import WorkspaceMember
from tests.helpers.tenant_isolation import (
    PROFILE_SCOPED_ROUTES,
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


async def _seed_workspace(session: AsyncSession, owner: User, name: str) -> UUID:
    session.add(owner)
    await session.flush()
    workspace = await WorkspaceService.create_workspace_for_owner(session, owner.id, name)
    return workspace.id


def _context(user_id: UUID, workspace_id: UUID, role: WorkspaceRole) -> WorkspaceContext:
    return WorkspaceContext(user_id=user_id, workspace_id=workspace_id, role=role)


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


def _user_snapshot(user_id: UUID, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="$argon2id$test-only",
        display_name=email.split("@", maxsplit=1)[0],
        is_active=True,
    )


@pytest.mark.asyncio
async def test_profile_and_child_tenant_isolation_in_services_and_database(
    db_session: AsyncSession,
) -> None:
    owner_a = _user("profile-a@example.test")
    owner_b = _user("profile-b@example.test")
    workspace_a = await _seed_workspace(db_session, owner_a, "Profile workspace A")
    workspace_b = await _seed_workspace(db_session, owner_b, "Profile workspace B")
    context_a = _context(owner_a.id, workspace_a, WorkspaceRole.OWNER)
    context_b = _context(owner_b.id, workspace_b, WorkspaceRole.OWNER)
    profile = await ProfileService.create(
        context_a,
        db_session,
        ProfileCreateRequest(type=ProfileType.CREATOR, name="Creator A"),
    )
    await ProfileService.create_item(
        context_a,
        db_session,
        profile.id,
        ProfileItemType.PRODUCT,
        ProfileItemCreateRequest(name="Product A"),
        expected_version=profile.version,
    )
    profile_events = list(
        await db_session.scalars(select(OutboxEvent).where(OutboxEvent.aggregate_id == profile.id))
    )
    assert {event.event_type for event in profile_events} == {
        "profile.created",
        "profile.updated",
    }
    assert all(set(event.payload) == {"profile_id"} for event in profile_events)

    with pytest.raises(NotFound):
        await ProfileService.get(context_b, db_session, profile.id)
    with pytest.raises(NotFound):
        await ProfileService.update(
            context_b,
            db_session,
            profile.id,
            expected_version=1,
            body=ProfilePatchRequest(name="Cross-tenant overwrite"),
        )
    with pytest.raises(NotFound):
        await ProfileService.create_item(
            context_b,
            db_session,
            profile.id,
            ProfileItemType.PRODUCT,
            ProfileItemCreateRequest(name="Cross-tenant child"),
            expected_version=profile.version,
        )

    savepoint = await db_session.begin_nested()
    db_session.add(
        ProfileProduct(
            id=_new_id(),
            workspace_id=workspace_b,
            profile_id=profile.id,
            name="Structurally invalid child",
            description="",
            item_metadata={},
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await savepoint.rollback()

    stored = await ProfileService.get(context_a, db_session, profile.id)
    assert stored.name == "Creator A"


@pytest.mark.asyncio
async def test_creator_without_business_context_then_add_context_via_api(
    db_session: AsyncSession,
) -> None:
    owner = _user("creator-context@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Creator context workspace")
    context = _context(owner.id, workspace_id, WorkspaceRole.OWNER)
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: owner
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/v1/workspaces/{workspace_id}/profiles",
            json={"type": "creator", "name": "Independent creator"},
        )
        assert created.status_code == 201
        profile_id = UUID(created.json()["id"])
        assert created.json()["version"] == 1
        assert created.headers["ETag"] == '"1"'
        read_profile = await client.get(f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}")
        assert read_profile.json()["version"] == 1
        assert read_profile.headers["ETag"] == '"1"'
        absent = await client.get(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context"
        )
        assert absent.status_code == 200 and absent.json() is None
        stored_before = await ProfileService.get(context, db_session, profile_id)
        version_before = stored_before.version
        updated = await client.put(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
            json={"commercial_objectives": [{"type": "sales", "priority": 1}]},
            headers={"If-Match": str(version_before)},
        )
        assert updated.status_code == 200
        assert updated.json()["commercial_objectives"] == [{"type": "sales", "priority": 1}]
        archived = await client.post(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/archive",
            headers={"If-Match": str(version_before + 1)},
        )
        assert archived.status_code == 200
        active_list = await client.get(f"/api/v1/workspaces/{workspace_id}/profiles?limit=1")
        archived_list = await client.get(
            f"/api/v1/workspaces/{workspace_id}/profiles?limit=1&archived=true"
        )
        assert active_list.status_code == archived_list.status_code == 200
        assert active_list.json()["items"] == []
        assert [item["id"] for item in archived_list.json()["items"]] == [str(profile_id)]
        stored_after = await ProfileService.get(
            context, db_session, profile_id, include_archived=True
        )

    assert stored_after.id == stored_before.id
    assert stored_after.type == "creator"
    assert stored_after.name == stored_before.name
    assert stored_after.version == version_before + 2


@pytest.mark.asyncio
async def test_all_profile_writes_require_current_parent_version(
    db_session: AsyncSession,
) -> None:
    owner = _user("profile-write-versions@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Versioned workspace")
    context = _context(owner.id, workspace_id, WorkspaceRole.OWNER)
    profile = await ProfileService.create(
        context, db_session, ProfileCreateRequest(type=ProfileType.CREATOR, name="Versioned")
    )
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: owner
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    root = f"/api/v1/workspaces/{workspace_id}/profiles/{profile.id}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def write(method: str, path: str, body=None):
            version = profile.version
            missing = await client.request(method, path, json=body)
            assert missing.status_code == 428
            malformed = await client.request(
                method, path, json=body, headers={"If-Match": "invalid"}
            )
            assert malformed.status_code == 422
            stale = await client.request(
                method, path, json=body, headers={"If-Match": str(version + 1)}
            )
            assert stale.status_code == 409
            assert stale.json()["current"]["version"] == version
            assert bool(stale.json()["current"]["archived_at"]) == bool(profile.archived_at)
            assert stale.headers["content-type"] == "application/problem+json"
            saved = await client.request(
                method, path, json=body, headers={"If-Match": str(version)}
            )
            assert saved.status_code in (200, 201, 204)
            assert saved.headers["etag"] == f'"{version + 1}"'
            assert profile.version == version + 1
            return saved

        await write("PUT", f"{root}/business-context", {"commercial_objectives": []})
        for segment in ("products", "services", "offers"):
            created = await write("POST", f"{root}/{segment}", {"name": segment})
            await write("DELETE", f"{root}/{segment}/{created.json()['id']}")
        await write("POST", f"{root}/archive")
        await write("POST", f"{root}/restore")


@pytest.mark.asyncio
async def test_stale_if_match_returns_current_profile_without_overwriting(
    db_session: AsyncSession,
) -> None:
    owner = _user("profile-version@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Version workspace")
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: owner
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/v1/workspaces/{workspace_id}/profiles",
            json={"type": "business", "name": "Original"},
        )
        profile_id = UUID(created.json()["id"])
        invalid_create = await client.post(
            f"/api/v1/workspaces/{workspace_id}/profiles",
            json={"type": "not-a-profile-type", "name": ""},
        )
        assert invalid_create.status_code == 422
        assert {error["field"] for error in invalid_create.json()["field_errors"]} >= {
            "type",
            "name",
        }
        missing_precondition = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
            json={"name": "No precondition"},
        )
        assert missing_precondition.status_code == 428
        invalid_update = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
            json={"name": ""},
            headers={"If-Match": "1"},
        )
        assert invalid_update.status_code == 422
        assert any(error["field"] == "name" for error in invalid_update.json()["field_errors"])
        latest = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
            json={"name": "Latest edit"},
            headers={"If-Match": "1"},
        )
        assert latest.status_code == 200
        stale = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
            json={"name": "Stale overwrite"},
            headers={
                "If-Match": "1",
                "X-Request-ID": "profile-conflict-1",
                "traceparent": "00-abcdefabcdefabcdefabcdefabcdefab-0123456789abcdef-01",
            },
        )

    assert stale.status_code == 409
    assert stale.headers["content-type"].startswith("application/problem+json")
    assert stale.json()["request_id"] == "profile-conflict-1"
    assert stale.json()["trace_id"] == "abcdefabcdefabcdefabcdefabcdefab"
    assert stale.json()["current"]["name"] == "Latest edit"
    assert stale.json()["current"]["version"] == 2
    current = await db_session.scalar(
        select(ContentProfile).where(
            ContentProfile.workspace_id == workspace_id,
            ContentProfile.id == profile_id,
        )
    )
    assert current.name == "Latest edit"
    assert current.version == 2
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        product = await client.post(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products",
            json={"name": "Concurrent product"},
            headers={"If-Match": "2"},
        )
        assert product.status_code == 201
        product_id = UUID(product.json()["id"])
        missing_child_precondition = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{product_id}",
            json={"name": "Missing precondition"},
        )
        assert missing_child_precondition.status_code == 428
        stale_child = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{product_id}",
            json={"name": "Stale child edit"},
            headers={"If-Match": "2"},
        )
        assert stale_child.status_code == 409
        assert stale_child.json()["current"]["version"] == 3
        current_child = await client.patch(
            f"/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/products/{product_id}",
            json={"name": "Current child edit"},
            headers={"If-Match": "3"},
        )
        assert current_child.status_code == 200
        assert current_child.headers["ETag"] == '"4"'


@pytest.mark.asyncio
async def test_nonmember_receives_404_for_every_profile_route(
    db_session: AsyncSession,
) -> None:
    owner = _user("profile-route-owner@example.test")
    outsider = _user("profile-route-outsider@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Profile route workspace")
    db_session.add(outsider)
    await db_session.flush()
    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = lambda: outsider
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        await assert_nonmember_routes_hidden(
            client, workspace_id=workspace_id, routes=PROFILE_SCOPED_ROUTES
        )


@pytest.mark.asyncio
async def test_profile_role_matrix_is_enforced_for_every_profile_route(
    db_session: AsyncSession,
) -> None:
    owner = _user("profile-matrix-owner@example.test")
    admin = _user("profile-matrix-admin@example.test")
    member = _user("profile-matrix-member@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Profile matrix workspace")
    db_session.add_all([admin, member])
    await db_session.flush()
    db_session.add_all(
        [
            WorkspaceMember(workspace_id=workspace_id, user_id=admin.id, role="ADMIN"),
            WorkspaceMember(workspace_id=workspace_id, user_id=member.id, role="MEMBER"),
        ]
    )
    await db_session.flush()
    owner_context = _context(owner.id, workspace_id, WorkspaceRole.OWNER)
    profile = await ProfileService.create(
        owner_context,
        db_session,
        ProfileCreateRequest(type=ProfileType.CREATOR, name="Matrix profile"),
    )
    item = await ProfileService.create_item(
        owner_context,
        db_session,
        profile.id,
        ProfileItemType.PRODUCT,
        ProfileItemCreateRequest(name="Matrix product"),
        expected_version=profile.version,
    )
    service_item = await ProfileService.create_item(
        owner_context,
        db_session,
        profile.id,
        ProfileItemType.SERVICE,
        ProfileItemCreateRequest(name="Matrix service"),
        expected_version=profile.version,
    )
    offer_item = await ProfileService.create_item(
        owner_context,
        db_session,
        profile.id,
        ProfileItemType.OFFER,
        ProfileItemCreateRequest(name="Matrix offer"),
        expected_version=profile.version,
    )
    profile_id = profile.id
    item_ids = {
        ProfileItemType.PRODUCT: item.id,
        ProfileItemType.SERVICE: service_item.id,
        ProfileItemType.OFFER: offer_item.id,
    }
    profile_version = profile.version
    actor_ids = {
        WorkspaceRole.OWNER: owner.id,
        WorkspaceRole.ADMIN: admin.id,
        WorkspaceRole.MEMBER: member.id,
    }
    actor_emails = {
        WorkspaceRole.OWNER: owner.email,
        WorkspaceRole.ADMIN: admin.email,
        WorkspaceRole.MEMBER: member.email,
    }
    actor = _user_snapshot(actor_ids[WorkspaceRole.OWNER], actor_emails[WorkspaceRole.OWNER])

    async def current_user() -> User:
        return actor

    app = create_app(Settings(_env_file=None))
    app.dependency_overrides[AuthService.get_current_user] = current_user
    app.dependency_overrides[database_session] = _override_session_with_savepoint(db_session)
    permission_by_route = {
        (
            "GET",
            "/api/v1/workspaces/{workspace_id}/profiles",
        ): WorkspacePermission.PROFILE_READ,
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/profiles",
        ): WorkspacePermission.PROFILE_CREATE,
        (
            "GET",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        ): WorkspacePermission.PROFILE_READ,
        (
            "PATCH",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}",
        ): WorkspacePermission.PROFILE_UPDATE,
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/archive",
        ): WorkspacePermission.PROFILE_ARCHIVE,
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/restore",
        ): WorkspacePermission.PROFILE_ARCHIVE,
        (
            "GET",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        ): WorkspacePermission.PROFILE_READ,
        (
            "PUT",
            "/api/v1/workspaces/{workspace_id}/profiles/{profile_id}/business-context",
        ): WorkspacePermission.PROFILE_UPDATE,
    }
    for item_type in ProfileItemType:
        root = f"/api/v1/workspaces/{{workspace_id}}/profiles/{{profile_id}}/{item_type.value}"
        permission_by_route[("GET", root)] = WorkspacePermission.PROFILE_READ
        permission_by_route[("POST", root)] = WorkspacePermission.PROFILE_CREATE
        permission_by_route[("PATCH", f"{root}/{{item_id}}")] = WorkspacePermission.PROFILE_UPDATE
        permission_by_route[("DELETE", f"{root}/{{item_id}}")] = WorkspacePermission.PROFILE_ARCHIVE

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for role in (WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.MEMBER):
            actor = _user_snapshot(actor_ids[role], actor_emails[role])
            for route in PROFILE_SCOPED_ROUTES:
                permission = permission_by_route[(route.method, route.path)]
                allowed = permission in ROLE_PERMISSIONS[role]
                outer = await db_session.begin_nested()
                try:
                    if route.path.endswith("/restore"):
                        await ProfileService.archive(
                            _context(actor_ids[role], workspace_id, role),
                            db_session,
                            profile_id,
                            expected_version=profile_version,
                        )
                    path = route.path.format(
                        workspace_id=workspace_id,
                        profile_id=profile_id,
                        item_id=next(
                            item_id
                            for item_type, item_id in item_ids.items()
                            if f"/{item_type.value}/{{item_id}}" in route.path
                        )
                        if "/{item_id}" in route.path
                        else "0199f000-0000-7000-8000-000000000096",
                    )
                    headers = route.headers
                    if route.method != "GET":
                        headers = {
                            "If-Match": str(
                                profile_version + (1 if route.path.endswith("/restore") else 0)
                            )
                        }
                    response = await client.request(
                        route.method,
                        path,
                        json=route.body,
                        headers=headers,
                    )
                    if not allowed:
                        expected_status = 403
                    elif route.method == "GET" or route.method == "PATCH":
                        expected_status = 200
                    elif route.method == "DELETE":
                        expected_status = 204
                    elif route.path == "/api/v1/workspaces/{workspace_id}/profiles":
                        expected_status = 201
                    elif route.path.endswith(("/products", "/services", "/offers")):
                        expected_status = 201
                    else:
                        expected_status = 200
                    assert response.status_code == expected_status, (
                        f"{role} {route.method} {route.path}: {response.status_code}"
                    )
                finally:
                    if outer.is_active:
                        await outer.rollback()


@pytest.mark.asyncio
async def test_maturity_transitions_and_processed_keys_are_idempotent(
    db_session: AsyncSession,
) -> None:
    owner = _user("profile-maturity@example.test")
    workspace_id = await _seed_workspace(db_session, owner, "Maturity workspace")
    context = _context(owner.id, workspace_id, WorkspaceRole.OWNER)
    profile = await ProfileService.create(
        context,
        db_session,
        ProfileCreateRequest(type=ProfileType.CREATOR, name="Maturity profile"),
    )
    idempotency_keys = [_new_id() for _ in range(4)]

    first = await ProfileService.record_verified_performance(
        context, db_session, profile.id, 4, idempotency_keys[0]
    )
    duplicate_first = await ProfileService.record_verified_performance(
        context, db_session, profile.id, 4, idempotency_keys[0]
    )
    assert first.verified_performance_count == duplicate_first.verified_performance_count == 4
    assert first.stage.value == duplicate_first.stage.value == "cold_start"

    early = await ProfileService.record_verified_performance(
        context, db_session, profile.id, 1, idempotency_keys[1]
    )
    await ProfileService.record_verified_performance(
        context, db_session, profile.id, 1, idempotency_keys[1]
    )
    assert early.verified_performance_count == 5
    assert early.stage.value == "early_growth"

    at_29 = await ProfileService.record_verified_performance(
        context, db_session, profile.id, 24, idempotency_keys[2]
    )
    mature = await ProfileService.record_verified_performance(
        context, db_session, profile.id, 1, idempotency_keys[3]
    )
    assert at_29.verified_performance_count == 29
    assert at_29.stage.value == "early_growth"
    assert mature.verified_performance_count == 30
    assert mature.stage.value == "mature"

    maturity_events = await db_session.scalar(
        select(func.count())
        .select_from(OutboxEvent)
        .where(
            OutboxEvent.event_type == "profile.maturity_changed",
            OutboxEvent.aggregate_id == profile.id,
        )
    )
    processed_keys = await db_session.scalar(
        select(func.count())
        .select_from(ProcessedEvent)
        .where(
            ProcessedEvent.consumer_name == "profile.verified_performance",
            ProcessedEvent.event_id.in_(idempotency_keys),
        )
    )
    audit_count = await db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.action == "profile.verified_performance_recorded",
            AuditLog.resource_id == str(profile.id),
        )
    )
    assert maturity_events == 2
    assert processed_keys == 4
    assert audit_count == 4
