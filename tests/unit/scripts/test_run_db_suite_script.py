"""Refusal-path tests for scripts/run_db_suite.sh. No Docker and no database: stubs only."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "run_db_suite.sh"
FAKE_PASSWORD = "zq-fake-Pw-7731-distinct"
EXISTING_TEST_FILE = "tests/unit/scripts/test_run_db_suite_script.py"


def _find_bash() -> str | None:
    bash = shutil.which("bash")
    if bash is None:
        return None
    try:
        probe = subprocess.run(
            [bash, "-c", "echo ok"], capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bash if probe.returncode == 0 and probe.stdout.strip() == "ok" else None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="a working bash is not available on PATH")

DOCKER_STUB = """#!/usr/bin/env bash
echo "$*" >> "$STUB_LOG"
case "$1" in
  info) [ "${STUB_DOCKER:-up}" = "up" ] && exit 0 || exit 1 ;;
  ps) [ "${STUB_EXISTING:-0}" = "1" ] && echo strativa-test-db; exit 0 ;;
esac
exit 0
"""

# Behaves like `uv run ...`: real python for the redaction filter, a fake suite otherwise.
UV_STUB = """#!/usr/bin/env bash
echo "uv $*" >> "$STUB_LOG"
if [ "$2" = "python" ] && [ "$3" = "-c" ]; then
  shift 2
  exec "$STUB_PYTHON" "$@"
fi
echo "connecting with password $TEST_DB_PASSWORD"
echo "==== 3 passed, 1 skipped in 0.5s ===="
exit 0
"""


def _run(
    tmp_path: Path,
    args: list[str],
    *,
    docker: str = "up",
    existing: bool = False,
    password: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    assert BASH is not None
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in (("docker", DOCKER_STUB), ("uv", UV_STUB)):
        stub = stubs / name
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "TEST_DB_PASSWORD"}
    env["PATH"] = str(stubs) + os.pathsep + env.get("PATH", "")
    env.update(
        STUB_LOG=str(log),
        STUB_DOCKER=docker,
        STUB_EXISTING="1" if existing else "0",
        STUB_PYTHON=sys.executable,
    )
    if password is not None:
        env["TEST_DB_PASSWORD"] = password
    result = subprocess.run(
        [BASH, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
        timeout=120,
        check=False,
    )
    calls = [line for line in log.read_text(encoding="utf-8").splitlines() if line]
    return result, calls


def test_no_password_exits_4_and_never_prints_a_password(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, [])
    assert result.returncode == 4
    assert FAKE_PASSWORD not in result.stdout + result.stderr
    assert "TEST_DB_PASSWORD" in result.stderr
    assert not any(c.startswith("compose") or c.startswith("rm") for c in calls)


def test_docker_down_exits_3(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, [], docker="down", password=FAKE_PASSWORD)
    assert result.returncode == 3
    assert FAKE_PASSWORD not in result.stdout + result.stderr
    assert calls == ["info"]


@pytest.mark.parametrize(
    "args",
    [
        ["tests/db/../../etc/passwd.py"],
        ["tests/db/../conftest.py"],
        ["tests/db/test_x.txt"],
        ["tests/db/does_not_exist_zz.py"],
        ["tests/unit/scripts/test_run_db_suite_script.py"],
        ["/etc/passwd"],
        ["all", "all"],
        ["all", EXISTING_TEST_FILE],
        ["--replace", "all", "all"],
        ["--password=hunter2"],
        ["--password", "hunter2"],
        ["--replace", "--password=hunter2"],
        ["all", "--replace"],
        ["-v"],
    ],
)
def test_invalid_arguments_exit_2(tmp_path: Path, args: list[str]) -> None:
    result, calls = _run(tmp_path, args, password=FAKE_PASSWORD)
    assert result.returncode == 2
    assert "hunter2" not in result.stdout + result.stderr
    assert FAKE_PASSWORD not in result.stdout + result.stderr
    assert calls == []


def test_existing_container_exits_5_without_replace(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, [], existing=True, password=FAKE_PASSWORD)
    assert result.returncode == 5
    assert not any(c.startswith("rm") or c.startswith("compose") for c in calls)


def test_replace_removes_only_the_named_container_and_cleans_up(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, ["--replace"], existing=True, password=FAKE_PASSWORD)
    assert result.returncode == 0, result.stderr
    assert [c for c in calls if c.startswith("rm")] == ["rm -f strativa-test-db"]
    assert any(c.startswith("compose") and " up -d --wait" in c for c in calls)
    assert calls[-1] == "compose -f compose.test-db.yaml down"
    assert "cleanup done" in result.stdout
    assert "Summary: 3 passed, 1 skipped" in result.stdout
    assert FAKE_PASSWORD not in result.stdout + result.stderr
    assert "[REDACTED]" in result.stdout


def test_script_text_has_no_destructive_or_env_file_access() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "rm -rf" not in text
    assert "docker volume" not in text
    assert "--volumes" not in text
    for line in text.splitlines():
        if re.search(r"\bdown\b", line) and "compose" in line:
            assert not re.search(r"\s-v\b|--volumes|--remove-orphans", line)
    # The only mention of an env file is the filename inside the fixed exit-4 message.
    env_lines = [line for line in text.splitlines() if re.search(r"\.env\b", line)]
    assert len(env_lines) == 1
    assert env_lines[0].lstrip().startswith("echo ")
    assert ".env.test.docker.local" in env_lines[0]
    assert not re.search(r"\b(cat|source)\b[^\n]*\.env|<\s*\S*\.env", text)
