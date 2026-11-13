"""AC-1 (INV-1): litellm is imported only by the future adapter package of ai_platform."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP_DIRECTORY = Path(__file__).parents[3] / "app"
ADAPTER_PARTS = ("ai_platform", "adapters")
_DYNAMIC_IMPORTERS = {"__import__", "import_module"}


def _is_litellm(name: str) -> bool:
    return name == "litellm" or name.startswith("litellm.")


def _literal_first_argument(node: ast.Call) -> str | None:
    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _imports_litellm(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(_is_litellm(a.name) for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if _is_litellm(node.module):
                lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            target = _literal_first_argument(node)
            if called in _DYNAMIC_IMPORTERS and target is not None and _is_litellm(target):
                lines.append(node.lineno)
    return lines


def find_litellm_violations(app_directory: Path) -> list[str]:
    violations: list[str] = []
    for source_path in sorted(app_directory.rglob("*.py")):
        parts = source_path.relative_to(app_directory).parts
        if parts[: len(ADAPTER_PARTS)] == ADAPTER_PARTS and len(parts) > len(ADAPTER_PARTS):
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        violations.extend(f"{source_path}:{line}" for line in _imports_litellm(tree))
    return violations


def test_litellm_is_imported_only_from_the_adapter_package() -> None:
    violations = find_litellm_violations(APP_DIRECTORY)
    assert not violations, "litellm may only be imported under app/ai_platform/adapters/:\n" + (
        "\n".join(violations)
    )


# --- negative self-tests: the scan must be able to fail ---

_FORMS = [
    "import litellm\n",
    "import litellm as engine\n",
    "import litellm.router\n",
    "from litellm import completion\n",
    "from litellm.router import Router\n",
    "def f():\n    import litellm\n",
    "import os, litellm\n",
    "import importlib\nimportlib.import_module('litellm')\n",
    "__import__('litellm.utils')\n",
]


@pytest.mark.parametrize("source", _FORMS)
@pytest.mark.parametrize("location", ["other_module/service.py", "ai_platform/router.py"])
def test_scan_flags_litellm_outside_the_adapter_package(
    tmp_path: Path, source: str, location: str
) -> None:
    target = tmp_path / "app" / location
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    assert len(find_litellm_violations(tmp_path / "app")) == 1


@pytest.mark.parametrize(
    "location", ["ai_platform/adapters/gateway.py", "ai_platform/adapters/x/y.py"]
)
def test_scan_allows_litellm_inside_the_adapter_package(tmp_path: Path, location: str) -> None:
    target = tmp_path / "app" / location
    target.parent.mkdir(parents=True)
    target.write_text("import litellm\n", encoding="utf-8")
    assert find_litellm_violations(tmp_path / "app") == []


def test_scan_does_not_treat_an_adapters_file_as_the_package(tmp_path: Path) -> None:
    target = tmp_path / "app" / "ai_platform" / "adapters.py"
    target.parent.mkdir(parents=True)
    target.write_text("import litellm\n", encoding="utf-8")
    assert len(find_litellm_violations(tmp_path / "app")) == 1


def test_scan_ignores_unrelated_names(tmp_path: Path) -> None:
    target = tmp_path / "app" / "mod" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("import litellm_like\nlitellm = 1\nfrom x import litellm\n", encoding="utf-8")
    assert find_litellm_violations(tmp_path / "app") == []
