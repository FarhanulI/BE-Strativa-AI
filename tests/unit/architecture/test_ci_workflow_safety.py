"""T-013: the CI workflow must stay free of secrets and unsafe triggers.

No requirement ID: T-013 is verification infrastructure and satisfies no requirement by itself.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[3] / ".github" / "workflows"
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])


def _code_lines(path: Path) -> list[str]:
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]


def test_ci_workflow_exists() -> None:
    assert (WORKFLOWS / "ci.yml").is_file()


def test_workflows_reference_no_secrets_and_no_privileged_trigger() -> None:
    for path in _workflow_files():
        text = "\n".join(_code_lines(path))
        assert "secrets." not in text, f"{path.name} references secrets"
        assert "pull_request_target" not in text, f"{path.name} uses pull_request_target"
        assert "workflow_run" not in text, f"{path.name} uses workflow_run"
        assert "github.token" not in text, f"{path.name} references the token explicitly"


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    for path in _workflow_files():
        uses = [
            line.split("uses:", 1)[1].split("#", 1)[0].strip()
            for line in _code_lines(path)
            if "uses:" in line
        ]
        assert uses, f"{path.name} uses no actions; update this test if that is intended"
        for reference in uses:
            _, _, ref = reference.partition("@")
            assert FULL_SHA.fullmatch(ref), f"{path.name}: {reference} is not SHA-pinned"


def test_workflows_default_to_read_only_contents_permission() -> None:
    for path in _workflow_files():
        lines = _code_lines(path)
        assert "permissions:" in lines, f"{path.name} lacks a top-level permissions block"
        index = lines.index("permissions:")
        assert lines[index + 1].strip() == "contents: read", path.name


def test_workflows_do_not_target_neon_or_real_providers() -> None:
    for path in _workflow_files():
        text = "\n".join(_code_lines(path)).lower()
        assert "neon" not in text, f"{path.name} mentions Neon (T-001 needs its own workflow)"
        assert "gemini_api_key" not in text
        assert "openai" not in text
