from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, ClassVar, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import SystemClock, UUID7Factory

_SENSITIVE_KEY = re.compile(
    r"password|token|secret|authorization|credential|api[_-]?key|private[_-]?key",
    re.I,
)
EventType = TypeVar("EventType", bound="DomainEvent")


class EventRegistry:
    def __init__(self) -> None:
        self._event_types: dict[tuple[str, int], type[DomainEvent]] = {}

    def register(self, event_model: type[EventType]) -> None:
        key = (event_model.event_type, event_model.event_version)
        if key in self._event_types:
            raise ValueError(f"Event already registered: {key[0]} v{key[1]}")
        self._event_types[key] = event_model

    def validate(self, event: DomainEvent) -> None:
        key = (event.event_type, event.event_version)
        if self._event_types.get(key) is not type(event):
            raise ValueError("Event type/version is not registered")


def _validate_safe_mapping(value: dict[str, Any]) -> dict[str, Any]:
    def check(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if _SENSITIVE_KEY.search(str(key)):
                    raise ValueError("Sensitive fields are not allowed in event data")
                check(nested)
        elif isinstance(item, list):
            for nested in item:
                check(nested)

    check(value)
    return value


class DomainEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: ClassVar[str]
    event_version: ClassVar[int] = 1
    aggregate_type: str
    aggregate_id: UUID
    workspace_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=SystemClock().now)

    def envelope(self, metadata: dict[str, str] | None = None) -> EventEnvelope:
        return EventEnvelope(
            event_id=UUID7Factory(SystemClock()).new(),
            event_type=self.event_type,
            event_version=self.event_version,
            aggregate_type=self.aggregate_type,
            aggregate_id=self.aggregate_id,
            workspace_id=self.workspace_id,
            occurred_at=self.occurred_at,
            payload=self.model_dump(
                mode="json",
                exclude={"aggregate_type", "aggregate_id", "workspace_id", "occurred_at"},
            ),
            metadata=metadata or {},
        )


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    event_type: str = Field(min_length=1)
    event_version: int = Field(ge=1)
    aggregate_type: str = Field(min_length=1)
    aggregate_id: UUID
    workspace_id: UUID | None = None
    occurred_at: datetime
    payload: dict[str, Any]
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("payload", "metadata")
    @classmethod
    def reject_sensitive_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_safe_mapping(value)

    def stream_fields(self) -> dict[str, str]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "event_version": str(self.event_version),
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "workspace_id": str(self.workspace_id) if self.workspace_id else "",
            "occurred_at": self.occurred_at.isoformat(),
            "payload": json.dumps(self.payload, separators=(",", ":")),
            "metadata": json.dumps(self.metadata, separators=(",", ":")),
        }


class DemoPingRequested(DomainEvent):
    event_type: ClassVar[str] = "foundation.demo_ping_requested"
    message: str


DEFAULT_EVENT_REGISTRY = EventRegistry()
DEFAULT_EVENT_REGISTRY.register(DemoPingRequested)