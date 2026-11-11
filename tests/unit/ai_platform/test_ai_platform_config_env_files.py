"""AiPlatformConfig reads the same env files as core Settings. Temporary files only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.ai_platform import AiPlatformConfig
from app.core import ConfigurationError, Settings

FILE_KEY = "pplx-file-only-DISTINCT-7731"
OTHER_KEY = "pplx-process-env-DISTINCT-4402"


@pytest.fixture(autouse=True)
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in list(os.environ):
        if name.upper().startswith("AI_") or name.upper() in {
            "APP_ENV",
            "TEST_DB_MODE",
            "PERPLEXITY_API_KEY",
            "GEMINI_API_KEY",
        }:
            monkeypatch.delenv(name)
    monkeypatch.setattr(Settings, "repository_root", staticmethod(lambda: tmp_path))
    return tmp_path


def test_values_from_dev_files_are_read(isolated_root: Path) -> None:
    (isolated_root / ".env.local").write_text(
        f"PERPLEXITY_API_KEY={FILE_KEY}\nAI_ASYNC_CONTENT_RETENTION_DAYS=7\nUNRELATED=1\n",
        encoding="utf-8",
    )
    config = AiPlatformConfig()
    assert config.async_content_retention_days == 7
    assert config.perplexity_api_key is not None
    assert config.perplexity_api_key.get_secret_value() == FILE_KEY


def test_process_environment_overrides_files(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_root / ".env.local").write_text(
        f"PERPLEXITY_API_KEY={FILE_KEY}\nAI_ASYNC_CONTENT_RETENTION_DAYS=7\n", encoding="utf-8"
    )
    monkeypatch.setenv("PERPLEXITY_API_KEY", OTHER_KEY)
    monkeypatch.setenv("AI_ASYNC_CONTENT_RETENTION_DAYS", "9")
    config = AiPlatformConfig()
    assert config.async_content_retention_days == 9
    assert config.perplexity_api_key is not None
    assert config.perplexity_api_key.get_secret_value() == OTHER_KEY


def test_file_key_never_appears_in_repr_str_or_errors(isolated_root: Path) -> None:
    (isolated_root / ".env.local").write_text(f"GEMINI_API_KEY={FILE_KEY}\n", encoding="utf-8")
    config = AiPlatformConfig()
    assert FILE_KEY not in repr(config)
    assert FILE_KEY not in str(config)
    (isolated_root / ".env.local").write_text(
        f"GEMINI_API_KEY={FILE_KEY}\nAI_ASYNC_CONTENT_RETENTION_DAYS={FILE_KEY}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError) as raised:
        AiPlatformConfig()
    assert FILE_KEY not in str(raised.value)
    assert "async_content_retention_days" in str(raised.value)


def test_test_mode_does_not_read_dot_env_local(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_root / ".env.local").write_text(
        "AI_ASYNC_CONTENT_RETENTION_DAYS=7\n", encoding="utf-8"
    )
    (isolated_root / ".env.test.local").write_text(
        "AI_GEMINI_BILLING_MODE=paid\n", encoding="utf-8"
    )
    monkeypatch.setenv("APP_ENV", "test")
    config = AiPlatformConfig()
    assert config.async_content_retention_days == 30
    assert config.gemini_billing_mode == "paid"


def test_local_mode_reads_docker_test_file(
    isolated_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (isolated_root / ".env.test.local").write_text(
        "AI_GEMINI_BILLING_MODE=paid\n", encoding="utf-8"
    )
    (isolated_root / ".env.test.docker.local").write_text(
        "AI_ASYNC_CONTENT_RETENTION_DAYS=11\n", encoding="utf-8"
    )
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("TEST_DB_MODE", "local")
    config = AiPlatformConfig()
    assert config.async_content_retention_days == 11
    assert config.gemini_billing_mode == "free_tier"


def test_env_file_none_reads_no_file(isolated_root: Path) -> None:
    (isolated_root / ".env.local").write_text(
        "AI_ASYNC_CONTENT_RETENTION_DAYS=7\n", encoding="utf-8"
    )
    assert AiPlatformConfig(_env_file=None).async_content_retention_days == 30
