"""Tests for scripts/sync_env_local.py. Temporary files only; the real .env.local is never read."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]

EXAMPLE = """\
# Required keys.
APP_ENV=
# Pooled URL.
DATABASE_URL=
# ai section
# Optional key, leave unset.
# AI_OPTIONAL_KEY=
# Set APP_ENV=test only in the test file.
AI_PLAIN=
"""


def _load() -> ModuleType:
    path = ROOT / "scripts" / "sync_env_local.py"
    spec = importlib.util.spec_from_file_location("sync_env_local", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sync_env_local = _load()


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE, encoding="utf-8")
    return example, tmp_path / ".env.local"


def test_adds_missing_names_with_comments(files: tuple[Path, Path]) -> None:
    example, local = files
    local.write_text("APP_ENV=dev\n", encoding="utf-8")
    added = sync_env_local.sync(example, local)
    assert added == ["DATABASE_URL", "AI_OPTIONAL_KEY", "AI_PLAIN"]
    text = local.read_text(encoding="utf-8")
    assert "# Pooled URL.\nDATABASE_URL=\n" in text
    assert "# Optional key, leave unset.\n# AI_OPTIONAL_KEY=\n" in text
    assert "\nAI_PLAIN=\n" in text


def test_keeps_existing_lines_untouched(files: tuple[Path, Path]) -> None:
    example, local = files
    original = "ZED=keep\nAPP_ENV=dev\n# AI_PLAIN=custom\nDATABASE_URL=sentinel-value\n"
    local.write_text(original, encoding="utf-8")
    added = sync_env_local.sync(example, local)
    assert added == ["AI_OPTIONAL_KEY"]
    text = local.read_text(encoding="utf-8")
    assert text.startswith(original)
    assert text.count("AI_PLAIN=") == 1


def test_commented_name_in_local_counts_as_present(files: tuple[Path, Path]) -> None:
    example, local = files
    local.write_text(
        "APP_ENV=dev\nDATABASE_URL=x\n# AI_OPTIONAL_KEY=\nAI_PLAIN=\n", encoding="utf-8"
    )
    assert sync_env_local.sync(example, local) == []


def test_prose_comment_is_not_a_variable(files: tuple[Path, Path]) -> None:
    example, local = files
    # "# Set APP_ENV=test ..." in the example must not create or satisfy a name.
    local.write_text("# Set DATABASE_URL=x in here\n", encoding="utf-8")
    assert "DATABASE_URL" in sync_env_local.sync(example, local)


def test_idempotent_on_second_run(files: tuple[Path, Path]) -> None:
    example, local = files
    local.write_text("APP_ENV=dev\n", encoding="utf-8")
    sync_env_local.sync(example, local)
    first = local.read_bytes()
    assert sync_env_local.sync(example, local) == []
    assert local.read_bytes() == first


def test_creates_file_when_missing(files: tuple[Path, Path]) -> None:
    example, local = files
    assert not local.exists()
    added = sync_env_local.sync(example, local)
    assert added == ["APP_ENV", "DATABASE_URL", "AI_OPTIONAL_KEY", "AI_PLAIN"]
    assert local.read_text(encoding="utf-8").splitlines()[:2] == ["# Required keys.", "APP_ENV="]


def test_handles_missing_trailing_newline(files: tuple[Path, Path]) -> None:
    example, local = files
    local.write_text("APP_ENV=dev", encoding="utf-8")
    sync_env_local.sync(example, local)
    assert local.read_text(encoding="utf-8").startswith("APP_ENV=dev\n# Pooled URL.\n")


def test_output_contains_names_only(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    example, local = files
    secret = "super-secret-value-123"
    local.write_text(f"APP_ENV={secret}\n", encoding="utf-8")
    added = sync_env_local.sync(example, local)
    print("added: " + ", ".join(added))
    assert secret not in capsys.readouterr().out


def test_main_prints_only_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    secret = "super-secret-value-123"
    (fake_root / ".env.local").write_text(f"APP_ENV={secret}\n", encoding="utf-8")
    fake_script = fake_root / "scripts" / "sync_env_local.py"
    monkeypatch.setattr(sync_env_local, "__file__", str(fake_script))
    assert sync_env_local.main() == 0
    out = capsys.readouterr().out
    assert secret not in out
    assert out.strip() == "added: DATABASE_URL, AI_OPTIONAL_KEY, AI_PLAIN"
    assert sync_env_local.main() == 0
    assert capsys.readouterr().out.strip() == "nothing to add"
