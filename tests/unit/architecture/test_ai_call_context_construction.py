"""AC-12 (INV-31, D-15): only app/ai_platform and app/rag may build a system AiCallContext.

No module outside ``app/ai_platform`` and ``app/rag`` may call ``AiCallContext.system(`` or
construct ``AiCallContext(`` directly. ``from_workspace`` and ``for_worker`` stay open to everyone.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP_DIRECTORY = Path(__file__).parents[3] / "app"
ALLOWED_MODULES = {"ai_platform", "rag"}
CONTEXT_NAME = "AiCallContext"


def _alias_names(tree: ast.AST) -> set[str]:
    """Local names bound to AiCallContext (the name itself and any ``as`` alias)."""
    names = {CONTEXT_NAME}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == CONTEXT_NAME and alias.asname:
                    names.add(alias.asname)
    return names


def _is_context(node: ast.expr, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    # a dotted reference such as app.ai_platform.AiCallContext
    return isinstance(node, ast.Attribute) and node.attr in names


def _violations_in(tree: ast.AST) -> list[int]:
    names = _alias_names(tree)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if _is_context(func, names):
            lines.append(node.lineno)  # AiCallContext(...)
        elif (
            isinstance(func, ast.Attribute)
            and func.attr == "system"
            and _is_context(func.value, names)
        ):
            lines.append(node.lineno)  # AiCallContext.system(...)
    return lines


def find_context_violations(app_directory: Path) -> list[str]:
    violations: list[str] = []
    for source_path in sorted(app_directory.rglob("*.py")):
        parts = source_path.relative_to(app_directory).parts
        if len(parts) > 1 and parts[0] in ALLOWED_MODULES:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        violations.extend(f"{source_path}:{line}" for line in _violations_in(tree))
    return violations


def test_only_ai_platform_and_rag_build_system_or_direct_contexts() -> None:
    violations = find_context_violations(APP_DIRECTORY)
    assert not violations, (
        "AiCallContext.system( and AiCallContext( are reserved to app/ai_platform and app/rag:\n"
        + "\n".join(violations)
    )


# --- negative self-tests: the scan must be able to fail ---

_IMPORT = "from app.ai_platform import AiCallContext\n"


def _scan(tmp_path: Path, relative: str, source: str) -> list[str]:
    target = tmp_path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return find_context_violations(tmp_path)


def test_scan_flags_a_system_context_in_another_module(tmp_path: Path) -> None:
    source = _IMPORT + "ctx = AiCallContext.system(request_id='r')\n"
    assert len(_scan(tmp_path, "profile/service.py", source)) == 1


def test_scan_flags_direct_construction_in_another_module(tmp_path: Path) -> None:
    source = _IMPORT + "ctx = AiCallContext(None, None, 'system', 'r')\n"
    assert len(_scan(tmp_path, "profile/service.py", source)) == 1


def test_scan_flags_an_aliased_import(tmp_path: Path) -> None:
    source = "from app.ai_platform import AiCallContext as C\nctx = C.system(request_id='r')\n"
    assert len(_scan(tmp_path, "a/mod.py", source)) == 1


def test_scan_flags_a_dotted_reference(tmp_path: Path) -> None:
    source = "import app.ai_platform\nctx = app.ai_platform.AiCallContext.system(request_id='r')\n"
    assert len(_scan(tmp_path, "b/mod.py", source)) == 1


def test_scan_allows_ai_platform_and_rag(tmp_path: Path) -> None:
    source = _IMPORT + "ctx = AiCallContext.system(request_id='r')\n"
    assert _scan(tmp_path, "rag/embed.py", source) == []
    assert _scan(tmp_path, "ai_platform/x.py", source) == []


def test_scan_allows_the_open_constructors_everywhere(tmp_path: Path) -> None:
    source = (
        _IMPORT
        + "a = AiCallContext.from_workspace(ws, request_id='r')\n"
        + "b = AiCallContext.for_worker(workspace_id=w, request_id='r')\n"
    )
    assert _scan(tmp_path, "profile/service.py", source) == []
