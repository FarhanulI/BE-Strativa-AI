from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from app.events_outbox import DEFAULT_EVENT_REGISTRY, DomainEvent


class UserRegistered(DomainEvent):
    event_type: ClassVar[str] = "auth.user_registered"
    user_id: UUID


DEFAULT_EVENT_REGISTRY.register(UserRegistered)