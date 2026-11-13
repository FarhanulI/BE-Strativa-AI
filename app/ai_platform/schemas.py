"""Output schema registry (spec 11): instance-based, no module-level state."""

from __future__ import annotations

from pydantic import BaseModel

from app.ai_platform.errors import AiTaskNotReady


class OutputSchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, dict[int, type[BaseModel]]] = {}

    def register(self, name: str, version: int, model: type[BaseModel]) -> None:
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise TypeError("output schema must be a pydantic BaseModel class")
        if model.model_config.get("extra") != "forbid":
            raise ValueError("output schema must forbid extra fields")
        if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
            raise ValueError("output schema version must be a positive integer")
        versions = self._schemas.setdefault(name, {})
        if version in versions:
            raise ValueError("output schema is already registered")
        versions[version] = model

    def get(self, name: str, version: int | None = None) -> type[BaseModel]:
        """``version=None`` means the highest registered version of ``name``."""
        versions = self._schemas.get(name)
        if not versions:
            raise AiTaskNotReady()
        chosen = max(versions) if version is None else version
        try:
            return versions[chosen]
        except KeyError:
            raise AiTaskNotReady() from None
