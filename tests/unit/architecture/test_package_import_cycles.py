"""T-016 step 1: the package import graph of ``app/`` must be acyclic.

Requirements strengthened: CORE-INV-11 and WS-AC-7 (boundary rules). The graph sees every import
statement, including those inside functions and methods, such as the lazy import in
``app/auth/__init__.py`` ``register_routes``. Limit: string-based dynamic imports are not visible
to an AST walk and are out of scope.

``REGISTRY_EXEMPT_FILES`` is a second visible list. ``app/db_migrations/alembic/env.py`` is the
Alembic metadata registry (ADR-0005): it must import every module's models, and every module imports
``db_migrations`` (``Base``, ``database_session``). Counting that one file turns the whole graph
into a single cycle of eight packages, so it is excluded, and a test checks that nothing in ``app/``
imports it (the exemption stays sound).

``KNOWN_CYCLES`` is the visible allowlist. It lists exactly one known cycle, auth and workspace
(conformance report B-1, ADR-0003). T-016 step 2 removes the entry; a stale entry (a listed cycle
that no longer exists) also fails, so the allowlist cannot be forgotten.
"""

from __future__ import annotations

from pathlib import Path

from tests.helpers.import_graph import build_package_graph, find_cycles

APP_DIRECTORY = Path(__file__).parents[3] / "app"

# The Alembic metadata registry (ADR-0005, owner review of T-016 step 1). Nothing may import it.
REGISTRY_EXEMPT_FILES = ("db_migrations/alembic/env.py",)

# T-016 step 2 removes this entry. Do not add entries without an owner-approved task.
KNOWN_CYCLES: set[frozenset[str]] = {frozenset({"auth", "workspace"})}


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_app_package_graph_has_no_cycle_except_the_known_one() -> None:
    cycles = set(find_cycles(build_package_graph(APP_DIRECTORY, exclude=REGISTRY_EXEMPT_FILES)))
    unexpected = cycles - KNOWN_CYCLES
    stale = KNOWN_CYCLES - cycles
    assert not unexpected, f"New package import cycle(s): {sorted(map(sorted, unexpected))}"
    assert not stale, (
        f"Allowlisted cycle(s) no longer exist, remove them: {sorted(map(sorted, stale))}"
    )


def test_registry_exemption_is_sound_nothing_imports_the_alembic_env() -> None:
    importers = [
        path.relative_to(APP_DIRECTORY).as_posix()
        for path in APP_DIRECTORY.rglob("*.py")
        if "app.db_migrations.alembic" in path.read_text(encoding="utf-8")
    ]
    assert importers == [], f"Files importing the Alembic registry: {importers}"
    for exempt in REGISTRY_EXEMPT_FILES:
        assert (APP_DIRECTORY / exempt).is_file(), f"Stale exemption: {exempt}"


def test_without_the_exemption_the_registry_makes_one_large_cycle() -> None:
    """Documents why the exemption exists; it fails if env.py stops importing the modules."""
    cycles = find_cycles(build_package_graph(APP_DIRECTORY))
    assert len(cycles) == 1 and {"auth", "workspace", "db_migrations"} <= cycles[0]


def test_known_cycle_edges_are_visible() -> None:
    graph = build_package_graph(APP_DIRECTORY, exclude=REGISTRY_EXEMPT_FILES)
    assert "workspace" in graph["auth"], "auth -> workspace edge (function-level) must be visible"
    assert "auth" in graph["workspace"]


def test_checker_detects_a_seeded_module_level_cycle(tmp_path: Path) -> None:
    root = tmp_path / "app"
    _write(root, "alpha/__init__.py", "from app.beta import thing\n")
    _write(root, "beta/__init__.py", "from app.alpha import other\n")
    assert find_cycles(build_package_graph(root)) == [frozenset({"alpha", "beta"})]


def test_checker_detects_a_seeded_function_level_cycle(tmp_path: Path) -> None:
    root = tmp_path / "app"
    _write(
        root, "alpha/__init__.py", "def go():\n    from app.beta import thing\n    return thing\n"
    )
    _write(root, "beta/__init__.py", "from app.alpha import go\n")
    assert find_cycles(build_package_graph(root)) == [frozenset({"alpha", "beta"})]


def test_checker_detects_a_method_level_and_three_node_cycle(tmp_path: Path) -> None:
    root = tmp_path / "app"
    _write(root, "a/__init__.py", "class A:\n    def m(self):\n        import app.b.mod\n")
    _write(root, "b/__init__.py", "from app.c import x\n")
    _write(root, "c/__init__.py", "from app import a\n")
    assert find_cycles(build_package_graph(root)) == [frozenset({"a", "b", "c"})]


def test_checker_resolves_relative_imports_and_ignores_same_package(tmp_path: Path) -> None:
    root = tmp_path / "app"
    _write(root, "a/__init__.py", "from .inner import x\n")
    _write(root, "a/inner.py", "from . import sibling\nfrom app.a.sibling import y\n")
    _write(root, "a/sibling.py", "")
    assert find_cycles(build_package_graph(root)) == []
    _write(root, "b/__init__.py", "from ..a import x\n")
    assert build_package_graph(root)["b"] == {"a"}


def test_checker_passes_an_acyclic_graph_and_ignores_third_party(tmp_path: Path) -> None:
    root = tmp_path / "app"
    _write(root, "core/__init__.py", "import json\nfrom pydantic import BaseModel\n")
    _write(root, "feature/__init__.py", "from app.core import Thing\n")
    graph = build_package_graph(root)
    assert graph == {"core": set(), "feature": {"core"}}
    assert find_cycles(graph) == []
