"""Provider helper methods of AiPlatformConfig (5b-1). Fake keys only; no real credential."""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from app.ai_platform import AiPlatformConfig
from app.core import ConfigurationError

FAKE_CHAT_KEY = "fake-chat-key-DISTINCT-7781"
FAKE_EMBED_KEY = "fake-embed-key-DISTINCT-4402"
CHAT = "gemini"
EMBED = "perplexity"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.upper().startswith("AI_") or name.upper() in {
            "PERPLEXITY_API_KEY",
            "PERPLEXITYAI_API_KEY",
            "GEMINI_API_KEY",
        }:
            monkeypatch.delenv(name)


def _config(**values: object) -> AiPlatformConfig:
    return AiPlatformConfig(_env_file=None, **values)


def test_api_key_for_returns_the_configured_secret() -> None:
    config = _config(gemini_api_key=FAKE_CHAT_KEY, perplexity_api_key=FAKE_EMBED_KEY)
    chat, embed = config.api_key_for(CHAT), config.api_key_for(EMBED)
    assert isinstance(chat, SecretStr) and chat.get_secret_value() == FAKE_CHAT_KEY
    assert isinstance(embed, SecretStr) and embed.get_secret_value() == FAKE_EMBED_KEY


def test_absent_key_is_none() -> None:
    config = _config()
    assert config.api_key_for(CHAT) is None
    assert config.api_key_for(EMBED) is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_key_is_none_and_not_configured(blank: str) -> None:
    config = _config(gemini_api_key=blank, perplexity_api_key=blank)
    assert config.api_key_for(CHAT) is None
    assert config.api_key_for(EMBED) is None
    assert not config.is_provider_configured(CHAT)
    assert not config.is_provider_configured(EMBED)


@pytest.mark.parametrize("unknown", ["", "nope", "GEMINI", "fakeprov", " gemini"])
def test_unknown_provider_has_no_key_and_is_not_configured(unknown: str) -> None:
    config = _config(gemini_api_key=FAKE_CHAT_KEY, perplexity_api_key=FAKE_EMBED_KEY)
    assert config.api_key_for(unknown) is None
    assert config.is_provider_configured(unknown) is False


def test_is_provider_configured_follows_each_key() -> None:
    config = _config(gemini_api_key=FAKE_CHAT_KEY)
    assert config.is_provider_configured(CHAT) is True
    assert config.is_provider_configured(EMBED) is False


@pytest.mark.parametrize("mode", ["free_tier", "paid"])
def test_chat_billing_mode_is_the_configured_one(mode: str) -> None:
    assert _config(gemini_billing_mode=mode).billing_mode_for(CHAT) == mode


def test_chat_billing_mode_defaults_to_free_tier() -> None:
    assert _config().billing_mode_for(CHAT) == "free_tier"


@pytest.mark.parametrize("mode", ["free_tier", "paid"])
def test_embedding_provider_is_always_paid(mode: str) -> None:
    assert _config(gemini_billing_mode=mode).billing_mode_for(EMBED) == "paid"


@pytest.mark.parametrize("unknown", ["", "nope", "fakeprov", "GEMINI"])
def test_billing_mode_for_unknown_provider_raises(unknown: str) -> None:
    with pytest.raises(ValueError) as caught:
        _config().billing_mode_for(unknown)
    assert unknown not in str(caught.value) or unknown == ""


def test_maps_cover_the_given_providers() -> None:
    config = _config(gemini_api_key=FAKE_CHAT_KEY, gemini_billing_mode="paid")
    assert config.provider_configured_map([CHAT, EMBED, "other"]) == {
        CHAT: True,
        EMBED: False,
        "other": False,
    }
    assert config.billing_mode_map([CHAT, EMBED]) == {CHAT: "paid", EMBED: "paid"}
    assert config.provider_configured_map([]) == {}
    assert config.billing_mode_map([]) == {}


def test_billing_mode_map_raises_for_an_unknown_provider() -> None:
    with pytest.raises(ValueError):
        _config().billing_mode_map([CHAT, "other"])


def test_no_key_value_in_repr_str_or_errors() -> None:
    config = _config(gemini_api_key=FAKE_CHAT_KEY, perplexity_api_key=FAKE_EMBED_KEY)
    shown = [repr(config), str(config)]
    shown += [repr(config.api_key_for(CHAT)), str(config.api_key_for(EMBED))]
    shown += [str(config.provider_configured_map([CHAT, EMBED]))]
    shown += [str(config.billing_mode_map([CHAT]))]
    with pytest.raises(ValueError) as caught:
        config.billing_mode_for("other")
    shown.append(str(caught.value))
    for text in shown:
        assert FAKE_CHAT_KEY not in text and FAKE_EMBED_KEY not in text


def test_invalid_configuration_error_does_not_echo_keys() -> None:
    with pytest.raises(ConfigurationError) as caught:
        _config(gemini_api_key=FAKE_CHAT_KEY, workspace_monthly_budget_usd="-1")
    assert FAKE_CHAT_KEY not in str(caught.value)
