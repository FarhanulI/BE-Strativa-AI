from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core import ConfigurationError, Settings

_PASSWORD_HASHER = PasswordHasher()
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=30)


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    return _PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(settings: Settings, user_id: UUID, session_id: UUID, now: datetime) -> str:
    secret = _jwt_secret(settings)
    return jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "exp": now + ACCESS_TOKEN_TTL,
        },
        secret,
        algorithm="HS256",
    )


def decode_access_token(settings: Settings, token: str) -> tuple[UUID, UUID]:
    claims = jwt.decode(
        token,
        _jwt_secret(settings),
        algorithms=["HS256"],
        options={"require": ["sub", "sid", "exp"]},
    )
    return UUID(claims["sub"]), UUID(claims["sid"])


def login_throttle_key(email: str, ip: str) -> str:
    digest = hashlib.sha256(f"{email.lower()}\0{ip}".encode()).hexdigest()
    return f"auth:login:{digest}"


def _jwt_secret(settings: Settings) -> str:
    if settings.auth_jwt_secret is None:
        raise ConfigurationError("AUTH_JWT_SECRET is required for authentication")
    secret = settings.auth_jwt_secret.get_secret_value()
    if len(secret.encode()) < 32:
        raise ConfigurationError("AUTH_JWT_SECRET must contain at least 32 bytes")
    return secret