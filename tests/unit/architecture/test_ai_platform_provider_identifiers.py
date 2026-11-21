"""AC-2 (INV-3): provider and model identifiers appear only in permitted locations.

The scan reads the raw text of every python file under app/ (comments and strings included).
Hits are reported as file and line only, never as the matching text.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from app.ai_platform.catalog import ModelCatalog
from tests.helpers.synthetic_catalog import FAKE_CHAT_MODEL, FAKE_PROVIDER, catalog_dict

APP_DIRECTORY = Path(__file__).parents[3] / "app"
PROVIDER_FRAGMENTS = ("gemini", "perplexity", "pplx", "openai", "anthropic", "claude")
ALLOWED_DIRECTORIES = (("ai_platform", "adapters"), ("ai_platform", "catalog"))
ALLOWED_FILES = (("ai_platform", "config.py"),)


def catalog_identifiers(catalog: ModelCatalog) -> frozenset[str]:
    """Provider and model identifiers of a catalog, for the scan below."""
    identifiers: set[str] = set()
    for entry in catalog.models():
        identifiers.add(entry.provider)
        identifiers.add(entry.model)
    return frozenset(identifiers)


def _is_allowed(parts: tuple[str, ...]) -> bool:
    if parts in ALLOWED_FILES:
        return True
    return any(
        parts[: len(directory)] == directory and len(parts) > len(directory)
        for directory in ALLOWED_DIRECTORIES
    )


def find_identifier_hits(app_directory: Path, extra_identifiers: Iterable[str] = ()) -> list[str]:
    needles = tuple(
        {fragment.lower() for fragment in (*PROVIDER_FRAGMENTS, *extra_identifiers) if fragment}
    )
    hits: list[str] = []
    for source_path in sorted(app_directory.rglob("*.py")):
        if _is_allowed(source_path.relative_to(app_directory).parts):
            continue
        for number, line in enumerate(source_path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if any(needle in lowered for needle in needles):
                hits.append(f"{source_path}:{number}")
    return hits


def _synthetic_identifiers() -> frozenset[str]:
    return catalog_identifiers(ModelCatalog.from_dict(catalog_dict()))


def test_no_provider_or_model_identifier_outside_permitted_locations() -> None:
    hits = find_identifier_hits(APP_DIRECTORY, _synthetic_identifiers())
    assert not hits, "provider or model identifiers outside permitted locations:\n" + "\n".join(
        hits
    )


# --- catalog identifier extraction ---


def test_catalog_identifiers_lists_providers_and_models() -> None:
    assert _synthetic_identifiers() >= {FAKE_PROVIDER, FAKE_CHAT_MODEL}


# --- negative self-tests: the scan must be able to fail ---


def _write(root: Path, relative: str, text: str) -> None:
    target = root / "app" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("fragment", PROVIDER_FRAGMENTS)
@pytest.mark.parametrize("location", ["other_module/service.py", "ai_platform/router.py"])
@pytest.mark.parametrize("style", ["code", "comment", "string", "upper"])
def test_scan_flags_provider_fragments_outside_permitted_locations(
    tmp_path: Path, fragment: str, location: str, style: str
) -> None:
    text = {
        "code": f"{fragment}_client = 1\n",
        "comment": f"# uses {fragment}\n",
        "string": f'NAME = "{fragment}"\n',
        "upper": f"X = '{fragment.upper()}'\n",
    }[style]
    _write(tmp_path, location, "x = 0\n" + text)
    hits = find_identifier_hits(tmp_path / "app")
    assert len(hits) == 1
    assert hits[0].endswith(":2")


@pytest.mark.parametrize(
    "location",
    [
        "ai_platform/adapters/gateway.py",
        "ai_platform/adapters/deep/x.py",
        "ai_platform/catalog/data.py",
        "ai_platform/config.py",
    ],
)
def test_scan_allows_permitted_locations(tmp_path: Path, location: str) -> None:
    _write(tmp_path, location, "x = 'gemini perplexity pplx openai anthropic claude'\n")
    assert find_identifier_hits(tmp_path / "app") == []


@pytest.mark.parametrize("location", ["ai_platform/adapters.py", "ai_platform/catalog.py"])
def test_scan_does_not_allow_files_named_like_permitted_packages(
    tmp_path: Path, location: str
) -> None:
    _write(tmp_path, location, "x = 'gemini'\n")
    assert len(find_identifier_hits(tmp_path / "app")) == 1


def test_scan_covers_extra_catalog_identifiers(tmp_path: Path) -> None:
    _write(tmp_path, "other_module/service.py", f"MODEL = '{FAKE_CHAT_MODEL.upper()}'\n")
    assert find_identifier_hits(tmp_path / "app") == []
    hits = find_identifier_hits(tmp_path / "app", _synthetic_identifiers())
    assert len(hits) == 1


def test_scan_extra_identifiers_are_also_permitted_in_allowed_locations(tmp_path: Path) -> None:
    _write(tmp_path, "ai_platform/adapters/a.py", f"M = '{FAKE_CHAT_MODEL}'\n")
    assert find_identifier_hits(tmp_path / "app", _synthetic_identifiers()) == []


def test_hits_report_file_and_line_only(tmp_path: Path) -> None:
    _write(tmp_path, "m/a.py", "SECRET = 'gemini-zz-leak'\n")
    (hit,) = find_identifier_hits(tmp_path / "app")
    assert "leak" not in hit and hit.endswith("a.py:1")
