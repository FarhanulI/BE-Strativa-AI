"""A deterministic unit estimator for tests: ceil(characters / 4). No provider library."""

from __future__ import annotations

from collections.abc import Sequence

from app.ai_platform.provider import ChatMessage


def _ceil_quarter(length: int) -> int:
    return -(-length // 4)


class CharCountEstimator:
    def estimate_messages(self, messages: Sequence[ChatMessage]) -> int:
        return _ceil_quarter(sum(len(message.content) for message in messages))

    def estimate_text(self, text: str) -> int:
        return _ceil_quarter(len(text))
