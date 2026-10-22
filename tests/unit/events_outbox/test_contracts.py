from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.events_outbox import DemoPingRequested, EventEnvelope, EventRegistry


def test_event_envelope_preserves_version_and_safe_json_fields() -> None:
    event = DemoPingRequested(
        aggregate_type="demo",
        aggregate_id=UUID("00000000-0000-7000-8000-000000000001"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        message="ready",
    )

    envelope = event.envelope({"request_id": "request-1"})
    fields = envelope.stream_fields()

    assert envelope.event_type == "foundation.demo_ping_requested"
    assert envelope.event_version == 1
    assert fields["payload"] == '{"message":"ready"}'
    assert fields["metadata"] == '{"request_id":"request-1"}'


def test_event_registry_requires_exact_registered_type_and_version() -> None:
    registry = EventRegistry()
    event = DemoPingRequested(
        aggregate_type="demo",
        aggregate_id=UUID("00000000-0000-7000-8000-000000000002"),
        message="registered",
    )
    registry.register(DemoPingRequested)
    registry.validate(event)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(DemoPingRequested)


def test_event_envelope_rejects_sensitive_fields() -> None:
    with pytest.raises(ValidationError, match="Sensitive fields"):
        EventEnvelope(
            event_id=UUID("00000000-0000-7000-8000-000000000003"),
            event_type="demo",
            event_version=1,
            aggregate_type="demo",
            aggregate_id=UUID("00000000-0000-7000-8000-000000000004"),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            payload={"ok": True},
            metadata={"api_key": "never-store"},
        )