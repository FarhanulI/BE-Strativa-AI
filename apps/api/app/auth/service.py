from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession, User
from app.auth.security import (
    decode_access_token,
    hash_refresh_token,
    login_throttle_key,
    new_refresh_token,
)
from app.core import (
    ConfigurationError,
    ExternalServiceError,
    NotFound,
    RateLimited,
    Settings,
    SystemClock,
    Unauthenticated,
    UUID7Factory,
    get_request_context,
)
from app.db_migrations import database_session
from app.observability_audit import AuditRecord, append_audit

_bearer = HTTPBearer(auto_error=False)
_RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('EXPIRE', key, window)
return 1
"""


class AuthService:
    @staticmethod
    async def get_current_user(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
        session: Annotated[AsyncSession, Depends(database_session)],
    ) -> User:
        if credentials is None:
            raise Unauthenticated("Authentication is required")
        settings: Settings = request.app.state.settings
        try:
            user_id, session_id = decode_access_token(settings, credentials.credentials)
        except (jwt.InvalidTokenError, ValueError, KeyError):
            raise Unauthenticated("Authentication is required") from None

        auth_session = await session.get(AuthSession, session_id)
        now = SystemClock().now()
        if (
            auth_session is None
            or auth_session.user_id != user_id
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= now
        ):
            raise Unauthenticated("Authentication is required")
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise Unauthenticated("Authentication is required")
        return user

    @staticmethod
    async def get_user(user_id: UUID, session: AsyncSession) -> User:
        user = await session.get(User, user_id)
        if user is None:
            raise NotFound("User was not found")
        return user

    @staticmethod
    async def find_user_by_email(email: str, session: AsyncSession) -> User | None:
        normalized = email.strip().lower()
        return await session.scalar(select(User).where(User.email == normalized))


async def allow_login_attempt(
    settings: Settings,
    *,
    email: str,
    ip: str,
    now: datetime,
) -> None:
    if settings.redis_url is None:
        raise ConfigurationError("REDIS_URL is required for login throttling")
    redis = Redis.from_url(settings.require_redis_url(), decode_responses=True)
    try:
        allowed = await redis.eval(
            _RATE_LIMIT_SCRIPT,
            1,
            login_throttle_key(email, ip),
            str(now.timestamp()),
            str(int(timedelta(minutes=15).total_seconds())),
            "10",
            new_refresh_token(),
        )
    except RedisError as error:
        raise ExternalServiceError("Login throttling is temporarily unavailable") from error
    finally:
        await redis.aclose()
    if not allowed:
        raise RateLimited("Too many login attempts; try again later")


async def create_auth_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    now: datetime,
    user_agent: str | None,
    ip: str | None,
    family_id: UUID | None = None,
) -> tuple[AuthSession, str]:
    token = new_refresh_token()
    session_id = UUID7Factory(SystemClock()).new()
    row = AuthSession(
        id=session_id,
        user_id=user_id,
        family_id=family_id or session_id,
        token_hash=hash_refresh_token(token),
        user_agent=user_agent[:512] if user_agent else None,
        ip=ip[:64] if ip else None,
        expires_at=now + timedelta(days=30),
    )
    session.add(row)
    await session.flush()
    return row, token


async def audit_auth_action(
    session: AsyncSession,
    *,
    action: str,
    actor_id: UUID | None,
    details: dict[str, object] | None = None,
) -> None:
    context = get_request_context()
    await append_audit(
        session,
        AuditRecord(
            actor_id=actor_id,
            actor_type="user" if actor_id else "system",
            action=action,
            resource_type="auth_session",
            request_id=context.request_id if context else "unknown",
            details=details or {},
        ),
    )


async def revoke_session_family(session: AsyncSession, family_id: UUID, now: datetime) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )