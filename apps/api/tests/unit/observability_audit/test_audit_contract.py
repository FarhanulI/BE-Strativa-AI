from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.observability_audit import AuditRecord
from app.observability_audit.logging import redact_sensitive_values


def test_audit_record_rejects_nested_sensitive_fields() -> None:
    with pytest.raises(ValidationError, match="Sensitive fields"):
        AuditRecord(
            actor_type="user",
            action="auth.login",
            resource_type="user",
            request_id="req-1",
            details={"context": {"private_api_key": "never-store"}},
        )


def test_log_processor_redacts_sensitive_keys_recursively() -> None:
    redacted = redact_sensitive_values(
        None,
        "info",
        {"request_id": "req-1", "nested": {"password": "secret", "count": 2}},
    )

    assert redacted == {
        "request_id": "req-1",
        "nested": {"password": "[REDACTED]", "count": 2},
    }