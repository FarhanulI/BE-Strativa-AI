from __future__ import annotations

import ast
import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import RFC_4122

import pytest
from fastapi import Request
from pydantic import SecretStr, ValidationError

from app.core import (
    AggregateRoot,
    AppEnvironment,
    ConfigurationError,
    Conflict,
    CursorPage,
    CursorParams,
    FakeClock,
    NotFound,
    RequestContext,
    Settings,
    UUID7Factory,
    ValueObject,
    domain_error_handler,
    get_request_context,
    new_uuid7,
    request_context_dependency,
    reset_request_context,
    set_request_context,
)


def test_uuid7_uses_injected_time_and_rfc_layout() -> None:
    now = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)
    identifier = new_uuid7(now)

    assert identifier.version == 7
    assert identifier.variant == RFC_4122
    assert identifier.int >> 80 == int(now.timestamp() * 1000)
    assert UUID7Factory(FakeClock(now)).new().version == 7


def test_uuid7_rejects_naive_or_out_of_range_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        new_uuid7(datetime(2026, 1, 1))

    with pytest.raises(ValueError, match="supported range"):
        new_uuid7(datetime(1960, 1, 1, tzinfo=UTC))


def test_fake_clock_requires_aware_time_and_can_advance() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    clock = FakeClock(now)

    assert clock.advance(timedelta(seconds=5)) == now + timedelta(seconds=5)
    with pytest.raises(ValueError, match="timezone-aware"):
        FakeClock(datetime(2026, 1, 1))


def test_entity_identity_and_value_object_equality() -> None:
    @dataclass(kw_only=True, eq=False)
    class Account(AggregateRoot):
        name: str

    @dataclass(frozen=True)
    class Email(ValueObject):
        value: str

    identifier = new_uuid7(datetime(2026, 1, 1, tzinfo=UTC))
    account = Account(id=identifier, name="A")
    assert account == Account(id=identifier, name="B")
    assert account != Account(id=new_uuid7(datetime(2026, 1, 2, tzinfo=UTC)), name="A")
    assert Email(value="a@example.test") == Email(value="a@example.test")
    assert Email(value="a@example.test") != Email(value="b@example.test")


def test_settings_allow_missing_infrastructure_and_hide_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "DATABASE_URL_DIRECT",
        "DATABASE_URL_UNPOOLED",
        "NEON_BRANCH_NAME",
        "REDIS_URL",
        "LOG_LEVEL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "SENTRY_DSN",
        "EMBEDDING_DIM",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)
    assert settings.database_url is None
    assert settings.redis_url is None
    assert settings.cors_origin_list == []
    with pytest.raises(ConfigurationError, match="DATABASE_URL is required"):
        settings.require_database_url()
    with pytest.raises(ConfigurationError, match="REDIS_URL is required"):
        settings.require_redis_url()

    configured = Settings(
        _env_file=None,
        database_url="postgresql://user:secret@host/db",
        neon_branch_name="dev",
    )
    assert isinstance(configured.database_url, SecretStr)
    assert "secret" not in repr(configured)
    assert configured.require_database_url() == "postgresql://user:secret@host/db"


def test_settings_validate_embedding_dimension_and_parse_cors() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, embedding_dim=0)

    settings = Settings(_env_file=None, cors_origins="https://one.test, https://two.test")
    assert settings.cors_origin_list == ["https://one.test", "https://two.test"]


def test_settings_load_local_env_file_after_base_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    (tmp_path / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")

    assert Settings().log_level == "DEBUG"


def test_settings_selects_test_env_file_and_requires_matching_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    for name in (
        "APP_ENV",
        "DATABASE_URL",
        "DATABASE_URL_DIRECT",
        "DATABASE_URL_UNPOOLED",
        "NEON_BRANCH_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    (tmp_path / ".env.test.local").write_text("APP_ENV=test\nLOG_LEVEL=WARNING\n", encoding="utf-8")

    settings = Settings(app_env="test")
    assert settings.log_level == "WARNING"
    assert settings.app_env.value == "test"

    with pytest.raises(ConfigurationError, match="NEON_BRANCH_NAME must match"):
        Settings(app_env="test", database_url="postgresql://test", neon_branch_name="dev")


def test_settings_accepts_unpooled_alias_without_leaking_conflicts() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://pooled",
        database_url_unpooled="postgresql://direct",
        neon_branch_name="dev",
    )
    assert settings.database_url_direct is not None
    assert settings.database_url_direct.get_secret_value() == "postgresql://direct"

    with pytest.raises(ConfigurationError) as error:
        Settings(
            _env_file=None,
            database_url_direct="postgresql://one-secret",
            database_url_unpooled="postgresql://another-secret",
            neon_branch_name="dev",
        )
    assert "one-secret" not in str(error.value)
    assert "another-secret" not in str(error.value)


def test_production_settings_ignore_env_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    (tmp_path / ".env").write_text("LOG_LEVEL=DEBUG\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("LOG_LEVEL=WARNING\n", encoding="utf-8")

    assert Settings().log_level == "INFO"


def test_test_and_production_environments_require_explicit_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None).app_env == AppEnvironment.DEV
    assert Settings(_env_file=None, app_env=AppEnvironment.TEST).app_env == AppEnvironment.TEST
    assert Settings(_env_file=None, app_env=AppEnvironment.PROD).app_env == AppEnvironment.PROD


def test_settings_discovers_test_environment_from_test_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    for name in ("APP_ENV", "DATABASE_URL", "DATABASE_URL_DIRECT", "DATABASE_URL_UNPOOLED"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("LOG_LEVEL=INFO\n", encoding="utf-8")
    (tmp_path / ".env.test.local").write_text("APP_ENV=test\nLOG_LEVEL=WARNING\n", encoding="utf-8")

    settings = Settings()

    assert settings.app_env == AppEnvironment.TEST
    assert settings.log_level == "WARNING"


def test_cursor_pagination_validation_and_generic_response() -> None:
    assert CursorParams(cursor="next", limit=10).limit == 10
    with pytest.raises(ValidationError):
        CursorParams(limit=0)

    page = CursorPage[int](items=[1, 2], next_cursor="next")
    assert page.items == [1, 2]
    assert page.next_cursor == "next"


@pytest.mark.asyncio
async def test_domain_error_handler_returns_problem_json() -> None:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/items/missing",
            "raw_path": b"/items/missing",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )

    response = await domain_error_handler(request, NotFound("Item does not exist"))
    assert response.status_code == 404
    assert response.media_type == "application/problem+json"
    assert b'"code":"not_found"' in response.body
    assert b'"instance":"/items/missing"' in response.body


@pytest.mark.asyncio
async def test_context_dependency_sets_and_resets_context() -> None:
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [(b"x-request-id", b"request-123")],
            "server": ("test", 80),
            "client": ("test", 1),
        }
    )
    dependency = request_context_dependency(request)

    context = await anext(dependency)
    assert context.request_id == "request-123"
    assert context.workspace_id is None
    assert get_request_context() == context

    await dependency.aclose()
    assert get_request_context() is None


@pytest.mark.asyncio
async def test_contextvars_are_isolated_between_async_tasks() -> None:
    async def task(request_id: str) -> str | None:
        token = set_request_context(RequestContext(request_id=request_id, actor_type="worker"))
        await asyncio.sleep(0)
        result = get_request_context()
        reset_request_context(token)
        return result.request_id if result else None

    assert await asyncio.gather(task("first"), task("second")) == ["first", "second"]


def test_conflict_has_stable_machine_code() -> None:
    assert Conflict("duplicate").code == "conflict"


def test_core_does_not_import_domain_module_internals() -> None:
    core_directory = Path(__file__).parents[3] / "app" / "core"
    for source_path in core_directory.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.modules.")
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith("app.modules.") for alias in node.names)