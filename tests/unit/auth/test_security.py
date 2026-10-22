from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest

from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    login_throttle_key,
    new_refresh_token,
    verify_password,
)
from app.core import Settings


def test_passwords_use_argon2id_and_never_verify_wrong_input() -> None:
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery staple")
    assert not verify_password(password_hash, "wrong password")


def test_access_token_has_identity_and_session_not_workspace_authority() -> None:
    settings = Settings(_env_file=None, auth_jwt_secret="unit-test-secret-that-is-long-enough")
    now = datetime.now(UTC)
    user_id = UUID("0199f000-0000-7000-8000-000000000001")
    session_id = UUID("0199f000-0000-7000-8000-000000000002")

    token = create_access_token(settings, user_id, session_id, now)
    claims = jwt.decode(
        token,
        settings.auth_jwt_secret.get_secret_value(),
        algorithms=["HS256"],
    )

    assert set(claims) == {"sub", "sid", "exp"}
    assert 899 <= claims["exp"] - int(now.timestamp()) <= 900
    assert decode_access_token(settings, token) == (user_id, session_id)


def test_expired_access_token_is_rejected() -> None:
    settings = Settings(_env_file=None, auth_jwt_secret="unit-test-secret-that-is-long-enough")
    now = datetime.now(UTC) - timedelta(minutes=16)
    token = create_access_token(
        settings,
        UUID("0199f000-0000-7000-8000-000000000003"),
        UUID("0199f000-0000-7000-8000-000000000004"),
        now,
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(settings, token)


def test_refresh_credentials_are_random_and_only_hashes_are_persisted() -> None:
    first = new_refresh_token()
    second = new_refresh_token()

    assert first != second
    assert hash_refresh_token(first) != first
    assert len(hash_refresh_token(first)) == 64


def test_login_throttle_key_does_not_contain_email_or_ip() -> None:
    key = login_throttle_key("Person@example.test", "192.0.2.20")

    assert "person@example.test" not in key
    assert "192.0.2.20" not in key
