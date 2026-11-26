"""AC-11 (INV-22): no direct system-time reads under app/ai_platform/.

All time comes from the injected Clock. The scan reads raw text (comments and strings
included) and reports file and line only, never the matching text.
"""

from __future__ import annotations

from pathlib import Path

APP_DIRECTORY = Path(__file__).parents[3] / "app"
SCAN_ROOT = ("ai_platform",)
FORBIDDEN_PATTERNS = (
    "datetime.now(",
    "datetime.utcnow(",
    "date.today(",
    "time.time(",
    "time.monotonic(",
    "time.time_ns(",
    "from time import",
)
# Relative paths (under app/) allowed to read the system time. Currently empty: the future
# SystemClock wiring file for build_ai_platform is added here, by path, when it exists.
ALLOWED_FILES: frozenset[tuple[str, ...]] = frozenset()


def find_clock_hits(
    app_directory: Path, allowed: frozenset[tuple[str, ...]] = ALLOWED_FILES
) -> list[str]:
    hits: list[str] = []
    for source_path in sorted((app_directory.joinpath(*SCAN_ROOT)).rglob("*.py")):
        if source_path.relative_to(app_directory).parts in allowed:
            continue
        for number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern in line for pattern in FORBIDDEN_PATTERNS):
                hits.append(f"{source_path}:{number}")
    return hits


def test_no_direct_system_time_reads_under_ai_platform() -> None:
    hits = find_clock_hits(APP_DIRECTORY)
    assert not hits, "direct system-time reads under app/ai_platform:\n" + "\n".join(hits)


def test_allowed_exception_list_is_empty() -> None:
    assert ALLOWED_FILES == frozenset()


def _write(root: Path, relative: str, text: str) -> None:
    target = root / "app" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_scan_flags_every_forbidden_pattern(tmp_path: Path) -> None:
    for index, pattern in enumerate(FORBIDDEN_PATTERNS):
        _write(tmp_path, f"ai_platform/sub/mod_{index}.py", f"x = 0\ny = {pattern}\n")
    hits = find_clock_hits(tmp_path / "app")
    assert len(hits) == len(FORBIDDEN_PATTERNS)
    assert all(hit.endswith(":2") for hit in hits)


def test_scan_ignores_files_outside_ai_platform(tmp_path: Path) -> None:
    _write(tmp_path, "other_module/clock.py", "x = datetime.now(UTC)\n")
    assert find_clock_hits(tmp_path / "app") == []


def test_scan_honours_an_explicit_allowed_file(tmp_path: Path) -> None:
    _write(tmp_path, "ai_platform/wiring.py", "x = datetime.now(UTC)\n")
    assert len(find_clock_hits(tmp_path / "app")) == 1
    assert find_clock_hits(tmp_path / "app", frozenset({("ai_platform", "wiring.py")})) == []
