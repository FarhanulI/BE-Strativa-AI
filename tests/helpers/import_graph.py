"""Package-level import graph of ``app/`` built from the AST (T-016).

Nodes are the top-level packages (or top-level modules) under ``app/``. An edge ``a -> b`` means a
file in ``a`` imports something from ``b``. Every ``import`` and ``from ... import`` statement
counts, including those inside functions, methods and ``if TYPE_CHECKING`` blocks, because
``ast.walk`` visits the whole tree.

Limit: imports that are built from strings at run time (``importlib.import_module(name)``,
``__import__(name)``) are not visible to an AST walk and are out of scope.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

Graph = dict[str, set[str]]


def _node_name(relative: Path) -> str:
    first = relative.parts[0]
    return first[:-3] if first.endswith(".py") else first


def _absolute_module(file_parts: tuple[str, ...], package: str, node: ast.ImportFrom) -> str | None:
    """Resolve a relative ``from`` import to an absolute dotted name."""
    if node.level == 0:
        return node.module
    parent = [package, *file_parts[:-1]]
    if node.level > 1:
        parent = parent[: len(parent) - (node.level - 1)]
    if not parent:
        return None
    return ".".join([*parent, node.module] if node.module else parent)


def _imported_modules(file_parts: tuple[str, ...], package: str, tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            module = _absolute_module(file_parts, package, node)
            if module is None:
                continue
            if module == package:
                # ``from app import auth`` names packages, so each alias is the dependency.
                for alias in node.names:
                    yield f"{package}.{alias.name}"
            else:
                yield module


def build_package_graph(root: Path, *, exclude: Iterable[str] = ()) -> Graph:
    """Graph for the package directory ``root`` (for example ``<repo>/app``).

    ``exclude`` lists files (POSIX paths relative to ``root``) that are left out of the graph.
    """
    skipped = set(exclude)
    package = root.name
    graph: Graph = {}
    for source in sorted(root.rglob("*.py")):
        relative = source.relative_to(root)
        if relative.as_posix() in skipped:
            continue
        node = _node_name(relative)
        graph.setdefault(node, set())
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for imported in _imported_modules(relative.parts, package, tree):
            parts = imported.split(".")
            if parts[0] != package or len(parts) < 2:
                continue
            target = parts[1]
            if target != node:
                graph[node].add(target)
                graph.setdefault(target, set())
    return graph


def find_cycles(graph: Mapping[str, Iterable[str]]) -> list[frozenset[str]]:
    """Strongly connected components with more than one node (Tarjan), sorted for stability."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[frozenset[str]] = []
    counter = 0

    def visit(start: str) -> None:
        nonlocal counter
        work = [(start, iter(sorted(graph.get(start, ()))))]
        index[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, neighbours = work[-1]
            advanced = False
            for neighbour in neighbours:
                if neighbour not in index:
                    index[neighbour] = low[neighbour] = counter
                    counter += 1
                    stack.append(neighbour)
                    on_stack.add(neighbour)
                    work.append((neighbour, iter(sorted(graph.get(neighbour, ())))))
                    advanced = True
                    break
                if neighbour in on_stack:
                    low[node] = min(low[node], index[neighbour])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                members = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    members.append(member)
                    if member == node:
                        break
                if len(members) > 1:
                    components.append(frozenset(members))

    for name in sorted(graph):
        if name not in index:
            visit(name)
    return sorted(components, key=lambda component: sorted(component))
