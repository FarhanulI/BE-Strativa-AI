"""T-018 / CP-1 (spec 10.1 rev 8): verification fields and the loader refusal of unverified entries.

Synthetic data only. The committed catalog is read in ``test_catalog_fitness.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.ai_platform.catalog import CatalogModel, ModelCatalog, load_catalog
from app.ai_platform.enums import AiTaskName
from app.core import ConfigurationError
from tests.helpers.synthetic_catalog import catalog_dict, chat_entry, embed_entry

DISTINCTIVE = "zz-distinctive-secret-9f3"


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_loader_refuses_an_unverified_entry_by_default_naming_only_field_paths(
    tmp_path: Path,
) -> None:
    data = catalog_dict(chat_entry(), embed_entry(model=DISTINCTIVE, verified=False))
    with pytest.raises(ConfigurationError) as caught:
        load_catalog(_write(tmp_path / "c.json", data))
    assert "models.1.verified" in str(caught.value)
    assert DISTINCTIVE not in str(caught.value)


def test_loader_refuses_a_disabled_unverified_entry_too(tmp_path: Path) -> None:
    data = catalog_dict(chat_entry(enabled=False, verified=False))
    with pytest.raises(ConfigurationError, match=r"models\.0\.verified"):
        load_catalog(_write(tmp_path / "c.json", data))


def test_loader_accepts_an_unverified_entry_only_when_asked(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.json", catalog_dict(chat_entry(verified=False)))
    assert load_catalog(path, allow_unverified=True).models()[0].verified is False


def test_allow_unverified_is_keyword_only_and_defaults_to_refusal(tmp_path: Path) -> None:
    path = _write(tmp_path / "c.json", catalog_dict(chat_entry(verified=False)))
    with pytest.raises(TypeError):
        load_catalog(path, True)  # type: ignore[misc]
    with pytest.raises(ConfigurationError):
        load_catalog(path)


def test_verified_catalog_loads_without_the_flag(tmp_path: Path) -> None:
    assert load_catalog(_write(tmp_path / "c.json", catalog_dict())).models()


@pytest.mark.parametrize("missing", ["verified", "verified_on"])
def test_verification_fields_are_required(missing: str) -> None:
    entry = chat_entry()
    del entry[missing]
    with pytest.raises(ConfigurationError, match=missing):
        ModelCatalog.from_dict(catalog_dict(entry))


@pytest.mark.parametrize("value", ["true", 1, "yes", None])
def test_verified_is_a_strict_boolean(value: object) -> None:
    with pytest.raises(ConfigurationError, match="verified"):
        ModelCatalog.from_dict(catalog_dict(chat_entry(verified=value)))


@pytest.mark.parametrize("value", ["2026-11-20T10:00:00", 20261120, "not-a-date", None])
def test_verified_on_is_a_date_not_a_timestamp(value: object) -> None:
    with pytest.raises(ConfigurationError, match="verified_on"):
        ModelCatalog.from_dict(catalog_dict(chat_entry(verified_on=value)))


def test_task_min_input_units_is_optional_and_strict() -> None:
    assert ModelCatalog.from_dict(catalog_dict()).task_min_input_units == {}
    good = catalog_dict()
    good["task_min_input_units"] = {"EMBED_TEXT": 10}
    assert ModelCatalog.from_dict(good).task_min_input_units == {AiTaskName.EMBED_TEXT: 10}
    for bad in ({"NOT_A_TASK": 10}, {"EMBED_TEXT": 0}, {"EMBED_TEXT": True}, {"EMBED_TEXT": 1.5}):
        data = catalog_dict()
        data["task_min_input_units"] = bad
        with pytest.raises(ConfigurationError, match="task_min_input_units"):
            ModelCatalog.from_dict(data)


def test_catalog_model_still_has_no_billing_or_token_field() -> None:
    fields = set(CatalogModel.model_fields) | set(ModelCatalog.model_fields)
    assert not any("billing" in name or "token" in name.lower() for name in fields)
