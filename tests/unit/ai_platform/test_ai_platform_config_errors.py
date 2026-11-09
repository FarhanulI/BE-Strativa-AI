from __future__ import annotations

import inspect
import os
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

import app.ai_platform as ai_platform
import app.ai_platform.config as config_module
import app.ai_platform.errors as errors_module
from app.ai_platform import (
    AiBudgetExceeded,
    AiContentRefused,
    AiErrorCode,
    AiInputTooLarge,
    AiModalityNotSupported,
    AiNoRoute,
    AiOutputInvalid,
    AiPlatformConfig,
    AiProviderNotConfigured,
    AiProviderUnavailable,
    AiTaskNotReady,
)
from app.core import (
    ConfigurationError,
    DomainError,
    ExternalServiceError,
    RateLimited,
    ValidationFailed,
)

FAKE_OPENAI = "sk-fake-openai-DISTINCT-91827"
FAKE_GEMINI = "fake-gemini-DISTINCT-55temp"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("AI_") or name.upper() in {"OPENAI_API_KEY", "GEMINI_API_KEY"}:
            monkeypatch.delenv(name)


def make(monkeypatch: pytest.MonkeyPatch, **env: str) -> AiPlatformConfig:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return AiPlatformConfig()


# --- config defaults ---


def test_defaults() -> None:
    config = AiPlatformConfig()
    assert config.workspace_limit_micro_usd == 25_000_000
    assert config.system_limit_micro_usd == 100_000_000
    assert config.async_content_retention_days == 30
    assert config.gemini_billing_mode == "free_tier"
    assert config.openai_api_key is None and config.gemini_api_key is None
    assert (config.max_provider_attempts, config.max_repair_attempts) == (3, 1)
    assert (config.lease_seconds, config.heartbeat_seconds) == (180, 60)
    assert config.purge_batch_size == 500
    assert config.context_safety_margin_percent == 10
    assert (
        config.breaker_failure_threshold,
        config.breaker_window_seconds,
        config.breaker_open_seconds,
    ) == (5, 60, 30)
    assert (config.async_reserved_stale_seconds, config.queued_stale_seconds) == (360, 300)
    assert (
        config.interactive_deadline_seconds,
        config.standard_deadline_seconds,
        config.batch_deadline_seconds,
    ) == (20, 60, 300)
    assert config.sync_stale_after_seconds == 420


# --- budget conversion ---


@pytest.mark.parametrize(
    ("text", "micro"),
    [
        ("12.345678", 12_345_678),
        ("0.000001", 1),
        ("0", 0),
        ("0.0", 0),
        ("1.2300000", 1_230_000),
        ("100", 100_000_000),
    ],
)
def test_budget_conversion_is_exact(
    monkeypatch: pytest.MonkeyPatch, text: str, micro: int
) -> None:
    config = make(
        monkeypatch, AI_WORKSPACE_MONTHLY_BUDGET_USD=text, AI_SYSTEM_MONTHLY_BUDGET_USD=text
    )
    assert config.workspace_limit_micro_usd == micro
    assert config.system_limit_micro_usd == micro
    assert isinstance(config.workspace_monthly_budget_usd, Decimal)
    assert isinstance(config.workspace_limit_micro_usd, int)


@pytest.mark.parametrize(
    "text",
    ["-1", "-0.000001", "1.2345678", "abc", "NaN", "Infinity", "-Infinity", "", "  ", "1e400"],
)
@pytest.mark.parametrize(
    "variable", ["AI_WORKSPACE_MONTHLY_BUDGET_USD", "AI_SYSTEM_MONTHLY_BUDGET_USD"]
)
def test_budget_rejections(monkeypatch: pytest.MonkeyPatch, variable: str, text: str) -> None:
    with pytest.raises(ConfigurationError) as raised:
        make(monkeypatch, **{variable: text})
    assert variable.removeprefix("AI_").lower() in str(raised.value)
    if text.strip():
        assert text not in str(raised.value)


def test_budget_rejects_float_input() -> None:
    with pytest.raises(ConfigurationError):
        AiPlatformConfig(workspace_monthly_budget_usd=12.5)  # type: ignore[arg-type]


def test_retention_must_be_at_least_one(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, AI_ASYNC_CONTENT_RETENTION_DAYS="1").async_content_retention_days == 1
    for bad in ("0", "-5", "x", ""):
        monkeypatch.setenv("AI_ASYNC_CONTENT_RETENTION_DAYS", bad)
        with pytest.raises(ConfigurationError):
            AiPlatformConfig()


# --- billing mode ---


def test_billing_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, AI_GEMINI_BILLING_MODE="paid").gemini_billing_mode == "paid"
    for bad in ("trial", "", "PAID ", "free"):
        monkeypatch.setenv("AI_GEMINI_BILLING_MODE", bad)
        with pytest.raises(ConfigurationError):
            AiPlatformConfig()


# --- timing validation ---


def test_sync_stale_must_exceed_longest_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, AI_SYNC_STALE_AFTER_SECONDS="301").sync_stale_after_seconds == 301
    for bad in ("300", "299", "1"):
        monkeypatch.setenv("AI_SYNC_STALE_AFTER_SECONDS", bad)
        with pytest.raises(ConfigurationError):
            AiPlatformConfig()


def test_sync_stale_follows_a_raised_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BATCH_DEADLINE_SECONDS", "420")
    with pytest.raises(ConfigurationError):
        AiPlatformConfig()


def test_heartbeat_must_be_less_than_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_HEARTBEAT_SECONDS", "180")
    with pytest.raises(ConfigurationError):
        AiPlatformConfig()
    monkeypatch.setenv("AI_HEARTBEAT_SECONDS", "179")
    assert AiPlatformConfig().heartbeat_seconds == 179


@pytest.mark.parametrize(
    "variable",
    [
        "AI_MAX_PROVIDER_ATTEMPTS",
        "AI_MAX_REPAIR_ATTEMPTS",
        "AI_LEASE_SECONDS",
        "AI_HEARTBEAT_SECONDS",
        "AI_PURGE_BATCH_SIZE",
        "AI_CONTEXT_SAFETY_MARGIN_PERCENT",
        "AI_BREAKER_FAILURE_THRESHOLD",
        "AI_BREAKER_WINDOW_SECONDS",
        "AI_BREAKER_OPEN_SECONDS",
        "AI_ASYNC_RESERVED_STALE_SECONDS",
        "AI_QUEUED_STALE_SECONDS",
        "AI_INTERACTIVE_DEADLINE_SECONDS",
        "AI_STANDARD_DEADLINE_SECONDS",
        "AI_BATCH_DEADLINE_SECONDS",
        "AI_SYNC_STALE_AFTER_SECONDS",
    ],
)
@pytest.mark.parametrize("bad", ["0", "-1"])
def test_non_positive_values_rejected(
    monkeypatch: pytest.MonkeyPatch, variable: str, bad: str
) -> None:
    monkeypatch.setenv(variable, bad)
    with pytest.raises(ConfigurationError):
        AiPlatformConfig()


# --- keys never leak ---


def test_keys_never_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make(monkeypatch, OPENAI_API_KEY=FAKE_OPENAI, GEMINI_API_KEY=FAKE_GEMINI)
    assert isinstance(config.openai_api_key, SecretStr)
    assert isinstance(config.gemini_api_key, SecretStr)
    assert config.openai_api_key.get_secret_value() == FAKE_OPENAI
    assert config.gemini_api_key.get_secret_value() == FAKE_GEMINI
    for text in (repr(config), str(config), repr(config.model_dump()), config.model_dump_json()):
        assert FAKE_OPENAI not in text and FAKE_GEMINI not in text


def test_keys_absent_for_blank_values(monkeypatch: pytest.MonkeyPatch) -> None:
    config = make(monkeypatch, OPENAI_API_KEY="", GEMINI_API_KEY="  ")
    assert config.openai_api_key is None and config.gemini_api_key is None


@pytest.mark.parametrize(
    "bad_env",
    [
        {"AI_WORKSPACE_MONTHLY_BUDGET_USD": "abc"},
        {"AI_GEMINI_BILLING_MODE": "trial"},
        {"AI_HEARTBEAT_SECONDS": "999"},
        {"AI_SYNC_STALE_AFTER_SECONDS": "10"},
        {"AI_LEASE_SECONDS": "0"},
    ],
)
def test_errors_never_contain_keys(
    monkeypatch: pytest.MonkeyPatch, bad_env: dict[str, str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI)
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_GEMINI)
    for name, value in bad_env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError) as raised:
        AiPlatformConfig()
    message = f"{raised.value} {raised.value!r}"
    assert FAKE_OPENAI not in message and FAKE_GEMINI not in message
    assert raised.value.__cause__ is None


def test_keys_are_not_prefixed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_OPENAI_API_KEY", FAKE_OPENAI)
    assert AiPlatformConfig().openai_api_key is None


# --- errors ---

ERROR_TABLE: list[tuple[type[Exception], type[Exception], int, str]] = [
    (AiBudgetExceeded, RateLimited, 429, "ai_budget_exceeded"),
    (AiNoRoute, ExternalServiceError, 502, "ai_no_route"),
    (AiProviderUnavailable, ExternalServiceError, 502, "ai_provider_unavailable"),
    (AiOutputInvalid, ExternalServiceError, 502, "ai_output_invalid"),
    (AiContentRefused, ExternalServiceError, 502, "ai_content_refused"),
    (AiInputTooLarge, ValidationFailed, 422, "ai_input_too_large"),
    (AiModalityNotSupported, ValidationFailed, 422, "ai_modality_not_supported"),
    (AiTaskNotReady, DomainError, 503, "ai_task_not_ready"),
]
FORBIDDEN_FRAGMENTS = (
    "gemini", "openai", "gpt", "claude", "litellm", "anthropic", "google", "embedding",
    "http", "key", "token", "prompt",
)  # fmt: skip


@pytest.mark.parametrize(("cls", "base", "status", "code"), ERROR_TABLE)
def test_error_classes(cls: Any, base: type[Exception], status: int, code: str) -> None:
    assert issubclass(cls, base) and issubclass(cls, DomainError)
    error = cls()
    assert error.status_code == status
    assert error.code == code
    assert error.detail and str(error) == error.detail
    lowered = (error.detail + error.title).lower()
    assert not any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS)


@pytest.mark.parametrize(("cls", "_base", "_status", "_code"), ERROR_TABLE)
def test_error_detail_cannot_be_injected(cls: Any, _base: Any, _status: Any, _code: Any) -> None:
    assert list(inspect.signature(cls).parameters) == []
    with pytest.raises(TypeError):
        cls("user text with gemini")
    with pytest.raises(TypeError):
        cls(detail="user text")
    assert cls().detail == cls().detail


def test_provider_not_configured_is_a_configuration_error() -> None:
    error = AiProviderNotConfigured()
    assert isinstance(error, ConfigurationError)
    assert not isinstance(error, DomainError)
    assert list(inspect.signature(AiProviderNotConfigured).parameters) == []
    lowered = str(error).lower()
    assert not any(fragment in lowered for fragment in FORBIDDEN_FRAGMENTS)
    with pytest.raises(TypeError):
        AiProviderNotConfigured("openai")  # type: ignore[call-arg]


def test_error_code_values_are_exactly_the_spec() -> None:
    assert [member.value for member in AiErrorCode] == [
        "provider_timeout",
        "provider_rate_limited",
        "provider_unavailable",
        "provider_auth_failed",
        "provider_not_configured",
        "provider_bad_request",
        "content_refused",
        "output_truncated",
        "output_invalid",
        "budget_exceeded",
        "no_route",
        "input_too_large",
        "lease_lost",
        "execution_abandoned",
    ]


# --- reflection, exports ---


def _names(module: Any) -> set[str]:
    names = {name for name in vars(module) if not name.startswith("__")}
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        names |= {name for name in vars(obj) if not name.startswith("__")}
        for field_name, field in getattr(obj, "model_fields", {}).items():
            names.add(field_name)
            for alias in (field.alias, field.validation_alias):
                if alias is not None:
                    names |= {str(c) for c in getattr(alias, "choices", [alias])}
    return names


@pytest.mark.parametrize("module", [config_module, errors_module])
def test_no_token_in_names(module: Any) -> None:
    assert [name for name in _names(module) if "token" in name.lower()] == []


def test_package_root_exports() -> None:
    assert sorted(ai_platform.__all__) == sorted(
        [
            "AiBudgetExceeded", "AiContentRefused", "AiErrorCode", "AiInputTooLarge",
            "AiModalityNotSupported", "AiNoRoute", "AiOutputInvalid", "AiPlatformConfig",
            "AiProviderNotConfigured", "AiProviderUnavailable", "AiTaskNotReady",
        ]
    )  # fmt: skip
    assert not hasattr(ai_platform, "AiRequest")
