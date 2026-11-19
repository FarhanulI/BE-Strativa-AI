"""The unit-estimator interface (spec 10.2 step 3, 12.2).

INTERNAL to ai_platform. The orchestrator needs an estimate of input units before any provider call
(the Router pads it with the safety margin). The real implementation counts with the provider
library and lives in the adapter, so it is not here: this module holds the interface only and no
default implementation. Both methods return non-negative ints.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.ai_platform.provider import ChatMessage


@runtime_checkable
class UnitEstimator(Protocol):
    def estimate_messages(self, messages: Sequence[ChatMessage]) -> int:
        """Estimated input units of a chat request."""
        ...

    def estimate_text(self, text: str) -> int:
        """Estimated input units of a single text (embeddings)."""
        ...
