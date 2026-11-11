"""Request and part types (spec 5.1, 13).

No field can name a provider or a model (INV-2). ``instructions`` is trusted; ``context`` and
text parts are untrusted data (11.1).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ai_platform.enums import AiTaskName, QualityClass

_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)


class AiContextBlock(BaseModel):
    model_config = _STRICT

    text: str  # UNTRUSTED DATA
    source_id: str | None = None  # opaque lineage reference, never interpreted


class MediaRef(BaseModel):
    """A reference to media. Bytes are never passed inline."""

    model_config = _STRICT

    kind: Literal["storage_key", "https_url"]
    value: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_value(self) -> MediaRef:
        if not self.value.strip():
            raise ValueError("value must not be blank")
        if self.kind == "https_url" and not self.value.startswith("https://"):
            raise ValueError("an https_url must start with https://")
        return self


class TextPart(BaseModel):
    model_config = _STRICT

    modality: Literal["text"]
    text: str


class ImagePart(BaseModel):
    model_config = _STRICT

    modality: Literal["image"]
    media: MediaRef
    mime_type: str = Field(min_length=1)


class VideoPart(BaseModel):
    model_config = _STRICT

    modality: Literal["video"]
    media: MediaRef
    mime_type: str = Field(min_length=1)


class AudioPart(BaseModel):
    model_config = _STRICT

    modality: Literal["audio"]
    media: MediaRef
    mime_type: str = Field(min_length=1)


AiPart = Annotated[TextPart | ImagePart | VideoPart | AudioPart, Field(discriminator="modality")]


class AiTaskRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task: AiTaskName
    instructions: str
    context: list[AiContextBlock] = []
    parts: list[AiPart] = []
    output_schema_version: int | None = Field(default=None, gt=0)
    max_output_units: int | None = Field(default=None, gt=0)
    quality_floor: QualityClass | None = None
    persist_result: bool = False

    @field_validator("task")
    @classmethod
    def _not_embedding(cls, value: AiTaskName) -> AiTaskName:
        if value is AiTaskName.EMBED_TEXT:
            raise ValueError("this task cannot be requested through AiTaskRequest")
        return value
