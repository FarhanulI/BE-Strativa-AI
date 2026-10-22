from __future__ import annotations

import ast
from pathlib import Path


def test_modules_import_other_modules_only_through_public_packages() -> None:
    app_directory = Path(__file__).parents[3] / "app"
    module_names = {
        path.name
        for path in app_directory.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    violations: list[str] = []

    for source_path in app_directory.rglob("*.py"):
        relative_parts = source_path.relative_to(app_directory).parts
        source_module = relative_parts[0] if len(relative_parts) > 1 else ""
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)

            for imported in imported_modules:
                parts = imported.split(".")
                if (
                    len(parts) > 2
                    and parts[0] == "app"
                    and parts[1] in module_names
                    and parts[1] != source_module
                ):
                    violations.append(f"{source_path}: {imported}")

    detail = "\n".join(violations)
    assert not violations, f"Cross-module imports must target package exports:\n{detail}"