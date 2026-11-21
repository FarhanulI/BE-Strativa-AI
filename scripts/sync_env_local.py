"""Append variables that exist in .env.example but are missing from .env.local.

Standard library only. Idempotent. Never modifies, reorders or deletes an existing line and never
prints a value from .env.local: only variable names are printed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# "NAME=value" or a commented placeholder "# NAME=value". Prose such as "# Set NAME=x" is ignored.
_VARIABLE = re.compile(r"^\s*(?:#\s*)?([A-Za-z_][A-Za-z0-9_]*)=")


def _variable_name(line: str) -> str | None:
    match = _VARIABLE.match(line)
    return match.group(1) if match else None


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _example_blocks(example_lines: list[str]) -> list[tuple[str, list[str]]]:
    """Return (name, lines) per first occurrence of a variable, with its leading comment lines."""
    blocks: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    comments: list[str] = []
    for line in example_lines:
        name = _variable_name(line)
        if name is not None:
            if name not in seen:
                seen.add(name)
                blocks.append((name, [*comments, line]))
            comments = []
        elif line.strip().startswith("#"):
            comments.append(line)
        else:
            comments = []
    return blocks


def sync(example: Path, local: Path) -> list[str]:
    """Append missing variables to ``local`` (created if absent). Return the names added."""
    example_lines = _read_lines(example)
    existing_text = local.read_text(encoding="utf-8") if local.is_file() else ""
    existing_names = {
        name for line in existing_text.splitlines() if (name := _variable_name(line)) is not None
    }
    newline = "\r\n" if "\r\n" in existing_text else "\n"

    added: list[str] = []
    addition: list[str] = []
    for name, lines in _example_blocks(example_lines):
        if name in existing_names:
            continue
        added.append(name)
        addition.extend(lines)

    if not local.is_file():
        # Created from .env.example: every name is missing, so this is the placeholders only.
        local.write_text(newline.join(addition) + newline if addition else "", encoding="utf-8")
        return added
    if addition:
        separator = "" if not existing_text or existing_text.endswith("\n") else newline
        with local.open("a", encoding="utf-8", newline="") as handle:
            handle.write(separator + newline.join(addition) + newline)
    return added


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    example = root / ".env.example"
    if not example.is_file():
        print(".env.example not found", file=sys.stderr)
        return 1
    added = sync(example, root / ".env.local")
    print("added: " + ", ".join(added) if added else "nothing to add")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
