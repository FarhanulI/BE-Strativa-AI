"""Synthetic model-catalog data for tests. Fake names and fake prices only."""

from __future__ import annotations

import copy
from typing import Any

FAKE_PROVIDER = "fakeprov"
FAKE_CHAT_MODEL = "fake-chat-zq1"
FAKE_EMBED_MODEL = "fake-embed-zq2"


def chat_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "provider": FAKE_PROVIDER,
        "model": FAKE_CHAT_MODEL,
        "enabled": True,
        "capabilities": ["text_generation", "structured_output", "reasoning"],
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "quality_tier": "standard",
        "context_window_units": 100_000,
        "max_output_units": 8_000,
        "supports_json_schema": True,
        "latency_p50_ms": 900,
        "input_micro_usd_per_million_units": 150_000,
        "output_micro_usd_per_million_units": 600_000,
        "price_source_url": "https://example.test/pricing",
        "price_checked_on": "2026-01-15",
    }
    entry.update(overrides)
    return entry


def embed_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "provider": FAKE_PROVIDER,
        "model": FAKE_EMBED_MODEL,
        "enabled": True,
        "capabilities": ["embedding"],
        "input_modalities": ["text"],
        "output_modalities": [],
        "quality_tier": "basic",
        "context_window_units": 8_000,
        "supports_json_schema": False,
        "latency_p50_ms": 200,
        "input_micro_usd_per_million_units": 50_000,
        "output_micro_usd_per_million_units": 0,
        "price_source_url": "https://example.test/pricing",
        "price_checked_on": "2026-01-15",
    }
    entry.update(overrides)
    return entry


def catalog_dict(*entries: dict[str, Any]) -> dict[str, Any]:
    return {
        "catalog_version": "test-1",
        "price_version": "test-prices-1",
        "models": copy.deepcopy(list(entries) or [chat_entry(), embed_entry()]),
    }
