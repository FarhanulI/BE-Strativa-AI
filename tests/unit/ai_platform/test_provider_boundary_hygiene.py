"""Hygiene scans for the step 5a modules: imports, names and root exports (INV-1, INV-3, INV-22)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import pytest

from app import ai_platform
from app.ai_platform import fake_provider, messages, provider, validation

PURE_MODULES = [provider, messages, validation]
ALL_MODULES = [*PURE_MODULES, fake_provider]
FORBIDDEN_IMPORT_ROOTS = {"litellm", "datetime", "time", "os"}
FAKE_FORBIDDEN_IMPORT_ROOTS = {"litellm", "datetime", "time", "os", "socket", "httpx", "requests"}
FORBIDDEN_ATTRIBUTE_CHAINS = {"os.environ", "os.getenv", "socket.socket"}


def _tree(module: Any) -> ast.AST:
    return ast.parse(Path(inspect.getsourcefile(module) or "").read_text(encoding="utf-8"))


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("module", PURE_MODULES, ids=lambda m: m.__name__)
def test_pure_modules_import_no_litellm_clock_or_os(module: Any) -> None:
    assert _imported_roots(_tree(module)) & FORBIDDEN_IMPORT_ROOTS == set()


def test_fake_provider_imports_no_network_clock_or_environment() -> None:
    assert _imported_roots(_tree(fake_provider)) & FAKE_FORBIDDEN_IMPORT_ROOTS == set()


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__)
def test_no_environment_or_socket_access(module: Any) -> None:
    chains: set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            chains.add(f"{node.value.id}.{node.attr}")
    assert chains & FORBIDDEN_ATTRIBUTE_CHAINS == set()


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.__name__)
def test_no_token_in_any_name_or_source_word(module: Any) -> None:
    source = Path(inspect.getsourcefile(module) or "").read_text(encoding="utf-8")
    assert "token" not in source.lower()
    names = {name for name in vars(module) if not name.startswith("__")}
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__:
            names |= {name for name in vars(cls) if not name.startswith("__")}
            names |= set(getattr(cls, "model_fields", {}))
    assert [name for name in names if "token" in name.lower()] == []


def test_package_root_exports_the_fake_and_nothing_else_from_these_modules() -> None:
    assert "FakeAiProvider" in ai_platform.__all__ and "ScriptedResponse" in ai_platform.__all__
    internal = {
        "ChatMessage",
        "ProviderClient",
        "ProviderCallError",
        "ProviderGenerationRequest",
        "ProviderGenerationResponse",
        "ValidationIssue",
        "ValidationOutcome",
        "validate_output",
        "build_generation_messages",
        "build_repair_messages",
        "default_marker_factory",
        "failure_kind_for_finish_reason",
        "response_mode_for",
        "response_schema_for",
        "RecordedCall",
    }
    assert internal & set(ai_platform.__all__) == set()
    assert not any(hasattr(ai_platform, name) for name in internal)
