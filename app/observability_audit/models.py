from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core import SystemClock, UUID7Factory
from app.db_migrations import GLOBAL, Base

_SENSITIVE_KEY = re.compile(
    r"password|token|secret|authorization|credential|api[_-]?key|private[_-]?key|database_url|redis_url",
    re.I,
)


def validate_audit_details(value: dict[str, object]) -> dict[str, object]:
    def check(item: object) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if _SENSITIVE_KEY.search(key):
                    raise ValueError("Sensitive fields are not allowed in audit details")
                check(nested)
        elif isinstance(item, list):
            for nested in item:
                check(nested)

    check(value)
    return value


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: UUID | None = None
    actor_type: str = Field(min_length=1, max_length=32)
    action: str = Field(min_length=1, max_length=160)
    resource_type: str = Field(min_length=1, max_length=100)
    resource_id: str | None = Field(default=None, max_length=200)
    workspace_id: UUID | None = None
    request_id: str = Field(min_length=1, max_length=200)
    event_id: UUID | None = None
    occurred_at: datetime = Field(default_factory=SystemClock().now)
    details: dict[str, object] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def reject_sensitive_details(cls, value: dict[str, object]) -> dict[str, object]:
        return validate_audit_details(value)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_occurred_at", "occurred_at"),
        Index("ix_audit_log_workspace_occurred_at", "workspace_id", "occurred_at"),
        Index("ix_audit_log_actor_occurred_at", "actor_id", "occurred_at"),
        Index(
            "ix_audit_log_resource_occurred_at",
            "resource_type",
            "resource_id",
            "occurred_at",
        ),
        {"info": {"tenant_scope": GLOBAL}},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=lambda: UUID7Factory(SystemClock()).new(),
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(200))
    workspace_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)