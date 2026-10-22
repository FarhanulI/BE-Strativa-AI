from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from app.events_outbox import DEFAULT_EVENT_REGISTRY, DomainEvent


class ProfileCreated(DomainEvent):
    event_type: ClassVar[str] = "profile.created"
    profile_id: UUID


class ProfileUpdated(DomainEvent):
    event_type: ClassVar[str] = "profile.updated"
    profile_id: UUID


class ProfileArchived(DomainEvent):
    event_type: ClassVar[str] = "profile.archived"
    profile_id: UUID


class ProfileRestored(DomainEvent):
    event_type: ClassVar[str] = "profile.restored"
    profile_id: UUID


class BusinessContextUpdated(DomainEvent):
    event_type: ClassVar[str] = "profile.business_context_updated"
    profile_id: UUID


class ProfileMaturityChanged(DomainEvent):
    event_type: ClassVar[str] = "profile.maturity_changed"
    profile_id: UUID


for event_model in (
    ProfileCreated,
    ProfileUpdated,
    ProfileArchived,
    ProfileRestored,
    BusinessContextUpdated,
    ProfileMaturityChanged,
):
    DEFAULT_EVENT_REGISTRY.register(event_model)