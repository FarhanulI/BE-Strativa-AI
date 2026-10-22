from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthService, AuthSession, User, UserRegistered
from app.auth.schemas import (
    AuthResponse,
    LoginRequest,
    MePatchRequest,
    MeResponse,
    RefreshResponse,
    RegisteredWorkspaceResponse,
    RegisterRequest,
    UserResponse,
)
from app.auth.security import (
    REFRESH_TOKEN_TTL,
    create_access_token,
    dummy_password_hash,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.auth.service import (
    allow_login_attempt,
    audit_auth_action,
    create_auth_session,
    revoke_session_family,
)
from app.core import Conflict, SystemClock, Unauthenticated
from app.db_migrations import database_session
from app.events_outbox import publish
from app.workspace import WorkspaceAccessService, WorkspaceService

_SESSION_COOKIE = "refresh_token"
_COOKIE_PATH = "/api/v1/auth"


def register_routes(app: FastAPI) -> None:
    @app.post("/api/v1/auth/register", response_model=AuthResponse, tags=["auth"])
    async def register(
        body: RegisterRequest,
        request: Request,
        response: Response,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> AuthResponse:
        normalized_email = body.email.strip().lower()
        duplicate = await AuthService.find_user_by_email(normalized_email, session)
        if duplicate is not None:
            raise Conflict("An account with this email already exists")
        now = SystemClock().now()
        user = User(
            email=normalized_email,
            password_hash=hash_password(body.password),
            display_name=body.display_name.strip(),
            is_active=True,
        )
        session.add(user)
        await session.flush()
        workspace = await WorkspaceService.create_workspace_for_owner(
            session, user.id, body.workspace_name
        )
        await publish(
            session,
            UserRegistered(aggregate_type="user", aggregate_id=user.id, user_id=user.id),
        )
        auth_session, refresh_token = await create_auth_session(
            session,
            user_id=user.id,
            now=now,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
        )
        access_token = create_access_token(
            request.app.state.settings, user.id, auth_session.id, now
        )
        _set_refresh_cookie(response, refresh_token)
        return AuthResponse(
            access_token=access_token,
            user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
            workspace=RegisteredWorkspaceResponse(
                id=workspace.id, name=workspace.name, slug=workspace.slug, role="OWNER"
            ),
        )

    @app.post("/api/v1/auth/login", response_model=AuthResponse, tags=["auth"])
    async def login(
        body: LoginRequest,
        request: Request,
        response: Response,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> AuthResponse:
        now = SystemClock().now()
        ip = request.client.host if request.client else "unknown"
        await allow_login_attempt(
            request.app.state.settings, email=body.email.strip().lower(), ip=ip, now=now
        )
        user = await AuthService.find_user_by_email(body.email, session)
        password_matches = (
            verify_password(user.password_hash, body.password)
            if user is not None
            else verify_password(dummy_password_hash(), body.password)
        )
        if user is None or not user.is_active or not password_matches:
            await audit_auth_action(
                session, action="auth.login_failure", actor_id=user.id if user else None
            )
            await session.commit()
            raise Unauthenticated("Email or password is incorrect")

        auth_session, refresh_token = await create_auth_session(
            session,
            user_id=user.id,
            now=now,
            user_agent=request.headers.get("user-agent"),
            ip=ip,
        )
        await audit_auth_action(session, action="auth.login_success", actor_id=user.id)
        workspaces = await WorkspaceAccessService.list_workspaces_for_user(session, user.id)
        _set_refresh_cookie(response, refresh_token)
        return AuthResponse(
            access_token=create_access_token(
                request.app.state.settings, user.id, auth_session.id, now
            ),
            user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
            workspace=(
                RegisteredWorkspaceResponse(
                    id=workspaces[0].id,
                    name=workspaces[0].name,
                    slug=workspaces[0].slug,
                    role=workspaces[0].role.value,
                )
                if len(workspaces) == 1
                else None
            ),
        )

    @app.post("/api/v1/auth/refresh", response_model=RefreshResponse, tags=["auth"])
    async def refresh(
        request: Request,
        response: Response,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> RefreshResponse:
        presented = request.cookies.get(_SESSION_COOKIE)
        if not presented:
            raise Unauthenticated("Refresh session is unavailable")
        auth_session = await session.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == hash_refresh_token(presented))
            .with_for_update()
        )
        if auth_session is None:
            raise Unauthenticated("Refresh session is unavailable")
        now = SystemClock().now()
        if auth_session.rotated_to_id is not None:
            await revoke_session_family(session, auth_session.family_id, now)
            await audit_auth_action(
                session,
                action="auth.refresh_reuse_detected",
                actor_id=auth_session.user_id,
            )
            await session.commit()
            raise Unauthenticated("Refresh session is unavailable")
        if auth_session.revoked_at is not None or auth_session.expires_at <= now:
            raise Unauthenticated("Refresh session is unavailable")

        user = await AuthService.get_user(auth_session.user_id, session)
        successor, refresh_token = await create_auth_session(
            session,
            user_id=user.id,
            now=now,
            user_agent=request.headers.get("user-agent"),
            ip=request.client.host if request.client else None,
            family_id=auth_session.family_id,
        )
        auth_session.rotated_to_id = successor.id
        auth_session.revoked_at = now
        _set_refresh_cookie(response, refresh_token)
        return RefreshResponse(
            access_token=create_access_token(request.app.state.settings, user.id, successor.id, now)
        )

    @app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
    async def logout(
        request: Request,
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        presented = request.cookies.get(_SESSION_COOKIE)
        if presented:
            auth_session = await session.scalar(
                select(AuthSession)
                .where(AuthSession.token_hash == hash_refresh_token(presented))
                .with_for_update()
            )
            if auth_session is not None and auth_session.revoked_at is None:
                auth_session.revoked_at = SystemClock().now()
        response = Response(status_code=204)
        _clear_refresh_cookie(response)
        return response

    @app.post("/api/v1/auth/logout-all", status_code=204, tags=["auth"])
    async def logout_all(
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> Response:
        now = SystemClock().now()
        await session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await audit_auth_action(session, action="auth.logout_all", actor_id=user.id)
        response = Response(status_code=204)
        _clear_refresh_cookie(response)
        return response

    @app.get("/api/v1/auth/me", response_model=MeResponse, tags=["auth"])
    async def me(
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> MeResponse:
        workspaces = await WorkspaceAccessService.list_workspaces_for_user(session, user.id)
        return MeResponse(
            user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
            workspaces=[
                RegisteredWorkspaceResponse(
                    id=workspace.id,
                    name=workspace.name,
                    slug=workspace.slug,
                    role=workspace.role.value,
                )
                for workspace in workspaces
            ],
        )

    @app.patch("/api/v1/auth/me", response_model=MeResponse, tags=["auth"])
    async def update_me(
        body: MePatchRequest,
        user: Annotated[User, Depends(AuthService.get_current_user)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> MeResponse:
        user.display_name = body.display_name
        await audit_auth_action(
            session,
            action="auth.display_name_updated",
            actor_id=user.id,
        )
        workspaces = await WorkspaceAccessService.list_workspaces_for_user(session, user.id)
        return MeResponse(
            user=UserResponse(id=user.id, email=user.email, display_name=user.display_name),
            workspaces=[
                RegisteredWorkspaceResponse(
                    id=workspace.id,
                    name=workspace.name,
                    slug=workspace.slug,
                    role=workspace.role.value,
                )
                for workspace in workspaces
            ],
        )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=int(REFRESH_TOKEN_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        _SESSION_COOKIE, path=_COOKIE_PATH, secure=True, httponly=True, samesite="lax"
    )