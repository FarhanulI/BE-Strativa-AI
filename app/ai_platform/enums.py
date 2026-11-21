"""Closed vocabularies of ai_platform (spec 5.1, 9, 13).

Nothing here names a provider or a model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class AiModality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class AiCapability(StrEnum):
    TEXT_GENERATION = "text_generation"
    REASONING = "reasoning"
    RETRIEVAL_GROUNDING = "retrieval_grounding"
    STRUCTURED_OUTPUT = "structured_output"
    EMBEDDING = "embedding"
    IMAGE_UNDERSTANDING = "image_understanding"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    AUDIO_TRANSCRIPTION = "audio_transcription"
    AUDIO_GENERATION = "audio_generation"


class AiTaskName(StrEnum):
    ANALYZE_MARKET_TRENDS = "ANALYZE_MARKET_TRENDS"
    GENERATE_CONTENT_BRIEF = "GENERATE_CONTENT_BRIEF"
    GENERATE_CHANNEL_EXECUTION = "GENERATE_CHANNEL_EXECUTION"
    GENERATE_CONTENT_DRAFT = "GENERATE_CONTENT_DRAFT"
    GENERATE_HOOK_VARIATIONS = "GENERATE_HOOK_VARIATIONS"
    ANALYZE_PERFORMANCE = "ANALYZE_PERFORMANCE"
    EXTRACT_AUDIENCE_SIGNALS = "EXTRACT_AUDIENCE_SIGNALS"
    SYNTHESIZE_SIGNALS = "SYNTHESIZE_SIGNALS"
    EMBED_TEXT = "EMBED_TEXT"  # internal: cannot be requested through AiTaskRequest


class QualityClass(StrEnum):
    """``basic`` < ``standard`` < ``high``. Ordering is by rank, not by string value."""

    BASIC = "basic"
    STANDARD = "standard"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return _QUALITY_RANK[self]

    # str defines its own comparisons, which would compare alphabetically, so all four are
    # overridden (functools.total_ordering would not replace them).
    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, QualityClass):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, QualityClass):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, QualityClass):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, QualityClass):
            return NotImplemented
        return self.rank >= other.rank


_QUALITY_RANK = {QualityClass.BASIC: 0, QualityClass.STANDARD: 1, QualityClass.HIGH: 2}


class LatencyClass(StrEnum):
    INTERACTIVE = "interactive"
    STANDARD = "standard"
    BATCH = "batch"


class CostClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskScope(StrEnum):
    WORKSPACE = "workspace"
    SYSTEM = "system"
