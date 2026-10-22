from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

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
    redis_url: SecretStr | None = Field(default=None, repr=False)
    log_level: str = "INFO"
    otel_exporter_otlp_endpoint: SecretStr | None = Field(default=None, repr=False)
    sentry_dsn: SecretStr | None = Field(default=None, repr=False)
    auth_jwt_secret: SecretStr | None = Field(default=None, repr=False)
    embedding_dim: int | None = Field(default=None, gt=0)
    cors_origins: str = ""

    def __init__(self, **values: Any) -> None:
        env_file_was_provided = "_env_file" in values
        root = self.repository_root()
        environment_override = values.get("app_env") or os.environ.get("APP_ENV")
        base_env = (
            dotenv_values(root / ".env")
            if not env_file_was_provided and environment_override != AppEnvironment.PROD
            else {}
        )
        test_env = (
            dotenv_values(root / ".env.test.local")
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
                env_files = (root / ".env", root / ".env.test.local")
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

        if self.database_url is not None or self.database_url_direct is not None:
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