from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit

from dotenv import dotenv_values
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class ConfigurationError(RuntimeError):
    pass


DEFAULT_MATURITY_COLD_START_THRESHOLD = 5
DEFAULT_MATURITY_MATURE_THRESHOLD = 30
TEST_DB_MODES = ("neon", "local")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_LOCAL_TEST_DATABASE = re.compile(r"[a-z][a-z0-9_]*_test")
_POSTGRES_SCHEMES = ("postgres", "postgresql", "postgresql+asyncpg")


@dataclass(frozen=True)
class DatabaseTarget:
    host: str | None
    unix_socket: bool
    database: str

    @property
    def is_local(self) -> bool:
        return self.unix_socket or (self.host in LOOPBACK_HOSTS)


def parse_database_target(url: str) -> DatabaseTarget:
    """Extract the host kind and database name. Errors never echo the URL."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
    except ValueError:
        raise ConfigurationError("Database URL is not a valid PostgreSQL URL") from None
    if parts.scheme not in _POSTGRES_SCHEMES:
        raise ConfigurationError("Database URL is not a valid PostgreSQL URL")
    database = unquote(parts.path.lstrip("/"))
    overridden = "hostaddr" in query or (host is not None and "host" in query)
    if overridden:
        return DatabaseTarget(host=None, unix_socket=False, database=database)
    socket_dir = query.get("host")
    unix_socket = host is None and socket_dir is not None and socket_dir.startswith("/")
    return DatabaseTarget(host=host, unix_socket=unix_socket, database=database)


def require_local_test_targets(urls: Sequence[str]) -> DatabaseTarget:
    targets = [parse_database_target(url) for url in urls]
    if not targets:
        raise ConfigurationError("Local test database mode requires a database URL")
    for target in targets:
        if not target.is_local:
            raise ConfigurationError(
                "Local test database mode requires a loopback or unix-socket host"
            )
        if _LOCAL_TEST_DATABASE.fullmatch(target.database) is None:
            raise ConfigurationError(
                "Local test database mode requires a database name ending in _test"
            )
    if len(set(targets)) != 1:
        raise ConfigurationError("Test database URLs must point at the same database")
    return targets[0]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=None,
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: AppEnvironment = AppEnvironment.DEV
    database_url: SecretStr | None = Field(default=None, repr=False)
    database_url_direct: SecretStr | None = Field(default=None, repr=False)
    database_url_unpooled: SecretStr | None = Field(default=None, repr=False)
    neon_branch_name: str | None = None
    test_db_mode: str = "neon"
    redis_url: SecretStr | None = Field(default=None, repr=False)
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: SecretStr | None = Field(default=None, repr=False)
    sentry_dsn: SecretStr | None = Field(default=None, repr=False)
    auth_jwt_secret: SecretStr | None = Field(default=None, repr=False)
    embedding_dim: int | None = Field(default=None, gt=0)
    cors_origins: str = ""
    maturity_cold_start_threshold: int = Field(default=DEFAULT_MATURITY_COLD_START_THRESHOLD, ge=0)
    maturity_mature_threshold: int = Field(default=DEFAULT_MATURITY_MATURE_THRESHOLD, gt=0)

    def __init__(self, **values: Any) -> None:
        env_file_was_provided = "_env_file" in values
        root = self.repository_root()
        environment_override = values.get("app_env") or os.environ.get("APP_ENV")
        base_env = (
            dotenv_values(root / ".env")
            if not env_file_was_provided and environment_override != AppEnvironment.PROD
            else {}
        )
        requested_mode = str(
            values.get("test_db_mode") or os.environ.get("TEST_DB_MODE") or "neon"
        )
        test_env_name = (
            ".env.test.docker.local" if requested_mode == "local" else ".env.test.local"
        )
        test_env = (
            dotenv_values(root / test_env_name)
            if not env_file_was_provided and environment_override is None
            else {}
        )
        selected_env = (
            environment_override
            or base_env.get("APP_ENV")
            or test_env.get("APP_ENV")
            or AppEnvironment.DEV
        )
        if not env_file_was_provided:
            env_files: tuple[Path, ...]
            if selected_env == AppEnvironment.DEV or selected_env == AppEnvironment.DEV.value:
                env_files = (root / ".env", root / ".env.local")
            elif selected_env == AppEnvironment.TEST or selected_env == AppEnvironment.TEST.value:
                env_files = (root / ".env", root / test_env_name)
            else:
                env_files = ()
            values["_env_file"] = tuple(path for path in env_files if path.is_file())

        explicit_app_env = "app_env" in values or "APP_ENV" in os.environ
        if not explicit_app_env and selected_env != AppEnvironment.PROD:
            explicit_app_env = base_env.get("APP_ENV") is not None
            explicit_app_env = explicit_app_env or test_env.get("APP_ENV") is not None
            if values.get("_env_file"):
                explicit_app_env = explicit_app_env or any(
                    dotenv_values(path).get("APP_ENV") is not None
                    for path in values["_env_file"]
                )
        super().__init__(**values)
        if self.test_db_mode != requested_mode:
            raise ConfigurationError("TEST_DB_MODE must be set in the process environment")
        if self.app_env in (AppEnvironment.TEST, AppEnvironment.PROD) and not explicit_app_env:
            raise ConfigurationError("APP_ENV=test or APP_ENV=prod must be explicitly provided")

    @staticmethod
    def repository_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @model_validator(mode="after")
    def validate_database_configuration(self) -> Settings:
        direct_url = self.database_url_direct
        unpooled_url = self.database_url_unpooled
        if direct_url is not None and unpooled_url is not None:
            if direct_url.get_secret_value() != unpooled_url.get_secret_value():
                raise ConfigurationError("DATABASE_URL_DIRECT and DATABASE_URL_UNPOOLED conflict")
        elif direct_url is None:
            self.database_url_direct = unpooled_url

        if self.maturity_mature_threshold <= self.maturity_cold_start_threshold:
            raise ConfigurationError("Maturity mature threshold must exceed cold start threshold")
        if self.test_db_mode not in TEST_DB_MODES:
            raise ConfigurationError("TEST_DB_MODE must be neon or local")
        if self.test_db_mode == "local":
            if self.app_env != AppEnvironment.TEST:
                raise ConfigurationError("TEST_DB_MODE=local requires APP_ENV=test")
            if self.neon_branch_name is not None:
                raise ConfigurationError("NEON_BRANCH_NAME must not be set in local test mode")
            urls = self.configured_database_urls()
            if urls:
                require_local_test_targets(urls)
        elif self.database_url is not None or self.database_url_direct is not None:
            expected_branch = {
                AppEnvironment.DEV: "dev",
                AppEnvironment.TEST: "test",
                AppEnvironment.PROD: "production",
            }.get(self.app_env)
            if expected_branch is None or self.neon_branch_name != expected_branch:
                raise ConfigurationError(
                    "NEON_BRANCH_NAME must match APP_ENV when a database URL is set"
                )
        return self

    def configured_database_urls(self) -> list[str]:
        candidates = (self.database_url, self.database_url_direct, self.database_url_unpooled)
        return [value.get_secret_value() for value in candidates if value is not None]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def require_database_url(self, *, direct: bool = False) -> str:
        value = self.database_url_direct if direct else self.database_url
        name = "DATABASE_URL_DIRECT" if direct else "DATABASE_URL"
        if value is None:
            raise ConfigurationError(f"{name} is required for this operation")
        return value.get_secret_value()

    def require_redis_url(self) -> str:
        if self.redis_url is None:
            raise ConfigurationError("REDIS_URL is required for this operation")
        return self.redis_url.get_secret_value()