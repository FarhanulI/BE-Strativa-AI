from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.ai_platform.catalog import CatalogModel, ModelCatalog, load_catalog
from app.ai_platform.enums import AiCapability, AiModality, QualityClass
from app.core import ConfigurationError
from tests.helpers.synthetic_catalog import (
    FAKE_CHAT_MODEL,
    FAKE_EMBED_MODEL,
    FAKE_PROVIDER,
    catalog_dict,
    chat_entry,
    embed_entry,
)

DISTINCTIVE = "zz-distinctive-secret-9f3"


def test_valid_catalog_loads_and_accessors_work() -> None:
    catalog = ModelCatalog.from_dict(
        catalog_dict(chat_entry(), embed_entry(), chat_entry(model="fake-off", enabled=False))
    )
    assert catalog.catalog_version == "test-1"
    assert catalog.price_version == "test-prices-1"
    assert len(catalog.models()) == 3
    chat = catalog.get(FAKE_PROVIDER, FAKE_CHAT_MODEL)
    assert chat is not None
    assert chat.quality_tier is QualityClass.STANDARD
    assert AiCapability.REASONING in chat.capabilities
    assert chat.input_modalities == {AiModality.TEXT}
    assert catalog.get(FAKE_PROVIDER, "missing") is None
    assert catalog.get("other", FAKE_CHAT_MODEL) is None
    assert len(catalog.models_for_provider(FAKE_PROVIDER)) == 3
    assert catalog.models_for_provider("other") == ()
    assert {m.model for m in catalog.enabled_models()} == {FAKE_CHAT_MODEL, FAKE_EMBED_MODEL}


def test_embedding_model_needs_no_max_output_units() -> None:
    embedding = ModelCatalog.from_dict(catalog_dict(embed_entry())).models()[0]
    assert embedding.max_output_units is None


def test_disabled_model_may_have_no_capabilities_or_max_output() -> None:
    entry = chat_entry(enabled=False, capabilities=[], max_output_units=None)
    assert ModelCatalog.from_dict(catalog_dict(entry)).models()[0].enabled is False


def test_catalog_has_no_billing_mode_or_token_field() -> None:
    fields = set(CatalogModel.model_fields) | set(ModelCatalog.model_fields)
    assert not any("billing" in name or "token" in name.lower() for name in fields)
    with pytest.raises(ConfigurationError):
        ModelCatalog.from_dict(catalog_dict(chat_entry(billing_mode="paid")))


def _bad(label: str, entries: list[dict[str, Any]], expected: str) -> Any:
    return pytest.param(entries, expected, id=label)


_IN_PRICE = "models.0.input_micro_usd_per_million_units"
_OUT_PRICE = "models.0.output_micro_usd_per_million_units"

BAD_ENTRIES = [
    _bad("duplicate", [chat_entry(), chat_entry()], "models.1"),
    _bad("float_price", [chat_entry(input_micro_usd_per_million_units=1.5)], _IN_PRICE),
    _bad("float_whole_price", [chat_entry(output_micro_usd_per_million_units=2.0)], _OUT_PRICE),
    _bad("string_price", [chat_entry(input_micro_usd_per_million_units="5")], _IN_PRICE),
    _bad("bool_price", [chat_entry(input_micro_usd_per_million_units=True)], _IN_PRICE),
    _bad("negative_price", [chat_entry(input_micro_usd_per_million_units=-1)], _IN_PRICE),
    _bad(
        "http_url",
        [chat_entry(price_source_url="http://example.test/p")],
        "models.0.price_source_url",
    ),
    _bad("zero_context", [chat_entry(context_window_units=0)], "models.0.context_window_units"),
    _bad("zero_max_output", [chat_entry(max_output_units=0)], "models.0.max_output_units"),
    _bad("zero_latency", [chat_entry(latency_p50_ms=0)], "models.0.latency_p50_ms"),
    _bad("string_enabled", [chat_entry(enabled="true")], "models.0.enabled"),
    _bad("uppercase_provider", [chat_entry(provider="Fake")], "models.0.provider"),
    _bad("empty_model", [chat_entry(model="")], "models.0.model"),
    _bad("blank_model", [chat_entry(model="  ")], "models.0.model"),
    _bad(
        "embedding_with_text_generation",
        [embed_entry(capabilities=["embedding", "text_generation"])],
        "models.0.capabilities",
    ),
    _bad(
        "structured_without_text_generation",
        [chat_entry(capabilities=["structured_output"])],
        "models.0.capabilities",
    ),
    _bad("enabled_without_capabilities", [chat_entry(capabilities=[])], "models.0.capabilities"),
    _bad(
        "enabled_generation_without_max_output",
        [chat_entry(max_output_units=None)],
        "models.0.max_output_units",
    ),
    _bad(
        "unknown_capability",
        [chat_entry(capabilities=["text_generation", "telepathy"])],
        "models.0.capabilities",
    ),
    _bad("unknown_modality", [chat_entry(input_modalities=["smell"])], "models.0.input_modalities"),
    _bad("unknown_quality", [chat_entry(quality_tier="ultra")], "models.0.quality_tier"),
    _bad("numeric_date", [chat_entry(price_checked_on=20260115)], "models.0.price_checked_on"),
    _bad("bad_date", [chat_entry(price_checked_on="not-a-date")], "models.0.price_checked_on"),
    _bad("extra_field", [chat_entry(**{DISTINCTIVE: 1})], "models.0.<unexpected field>"),
]


@pytest.mark.parametrize(("entries", "expected_path"), BAD_ENTRIES)
def test_invalid_entries_are_rejected_with_paths_only(
    entries: list[dict[str, Any]], expected_path: str
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        ModelCatalog.from_dict(catalog_dict(*entries))
    message = str(caught.value)
    assert expected_path in message
    assert DISTINCTIVE not in message


@pytest.mark.parametrize("field", ["catalog_version", "price_version"])
@pytest.mark.parametrize("value", ["", "   "])
def test_empty_versions_are_rejected(field: str, value: str) -> None:
    data = catalog_dict()
    data[field] = value
    with pytest.raises(ConfigurationError) as caught:
        ModelCatalog.from_dict(data)
    assert field in str(caught.value)


def test_missing_and_extra_top_level_keys_are_rejected() -> None:
    data = catalog_dict()
    del data["models"]
    with pytest.raises(ConfigurationError, match="models"):
        ModelCatalog.from_dict(data)
    data = catalog_dict()
    data[DISTINCTIVE] = 1
    with pytest.raises(ConfigurationError) as caught:
        ModelCatalog.from_dict(data)
    assert DISTINCTIVE not in str(caught.value)


@pytest.mark.parametrize("data", [[], None, "text", 5])
def test_non_object_root_is_rejected(data: Any) -> None:
    with pytest.raises(ConfigurationError, match="<root>"):
        ModelCatalog.from_dict(data)


def test_distinctive_values_never_appear_in_errors() -> None:
    entry = chat_entry(
        provider=DISTINCTIVE.upper(),
        quality_tier=DISTINCTIVE,
        price_source_url=DISTINCTIVE,
        capabilities=[DISTINCTIVE],
        price_checked_on=DISTINCTIVE,
    )
    with pytest.raises(ConfigurationError) as caught:
        ModelCatalog.from_dict(catalog_dict(entry))
    assert DISTINCTIVE not in str(caught.value).lower()


def test_catalog_is_immutable() -> None:
    catalog = ModelCatalog.from_dict(catalog_dict())
    with pytest.raises(ValidationError):
        catalog.catalog_version = "x"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        catalog.models()[0].enabled = False  # type: ignore[misc]
    assert isinstance(catalog.models(), tuple)
    assert isinstance(catalog.models()[0].capabilities, frozenset)


# --- loader ---


def test_load_catalog_reads_a_valid_json_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog_dict()), encoding="utf-8")
    catalog = load_catalog(path)
    assert len(catalog.models()) == 2
    with pytest.raises(ValidationError):
        catalog.price_version = "x"  # type: ignore[misc]


def test_load_catalog_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as caught:
        load_catalog(tmp_path / "absent.json")
    assert str(caught.value) == "The AI model catalog file could not be read"


def test_load_catalog_unreadable_path_is_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="could not be read"):
        load_catalog(tmp_path)


def test_load_catalog_non_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigurationError, match="could not be read"):
        load_catalog(path)


def test_load_catalog_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text('{"catalog_version": ' + DISTINCTIVE, encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_catalog(path)
    assert str(caught.value) == "The AI model catalog file is not valid JSON"


def test_load_catalog_bad_entry(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(catalog_dict(chat_entry(price_source_url=DISTINCTIVE))), encoding="utf-8"
    )
    with pytest.raises(ConfigurationError) as caught:
        load_catalog(path)
    assert str(caught.value) == (
        "Invalid AI model catalog; offending fields: models.0.price_source_url"
    )


def test_load_catalog_float_price_in_json(tmp_path: Path) -> None:
    path = tmp_path / "catalog.json"
    text = json.dumps(catalog_dict()).replace("150000", "150000.0")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="input_micro_usd_per_million_units"):
        load_catalog(path)
