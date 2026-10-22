from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for arguments in (
        ["ruff", "check", "app", "tests", "scripts"],
        ["mypy"],
        ["pytest", "-m", "not db"],
    ):
        result = subprocess.run([sys.executable, "-m", *arguments], cwd=root, check=False)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()