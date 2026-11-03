from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import CHAR

from app.core import SystemClock, UUID7Factory
from app.db_migrations import TENANT_SCOPED, Base

SCOPE_WORKSPACE_RULE = "(scope = 'workspace') = (workspace_id IS NOT NULL)"


def _new_id() -> UUID:
    return UUID7Factory(SystemClock()).new()


class AiRequest(Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        CheckConstraint("scope IN ('workspace','system')", name="scope"),
        CheckConstraint(SCOPE_WORKSPACE_RULE, name="scope_workspace"),
        CheckConstraint("status IN ('queued','running','succeeded','failed')", name="status"),
        CheckConstraint("mode IN ('sync','async')", name="mode"),
        CheckConstraint("actor_type IN ('user','system','worker')", name="actor_type"),
        CheckConstraint(
            "input_units >= 0 AND output_units >= 0 AND cost_micro_usd >= 0 "
            "AND attempt_count >= 0 AND lease_epoch >= 0",
            name="nonneg",
        ),
        CheckConstraint("(mode = 'async') = (idempotency_key IS NOT NULL)", name="async_key"),
        CheckConstraint(
            "(mode = 'async') = (request_fingerprint IS NOT NULL)", name="async_fingerprint"
        ),
        CheckConstraint(
            "task = 'EMBED_TEXT' OR "
            "(output_schema_name IS NOT NULL AND output_schema_version IS NOT NULL)",
            name="schema_name",
        ),
        CheckConstraint(
            "mode <> 'async' OR status <> 'running' OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="running_lease",
        ),
        CheckConstraint(
            "mode = 'async' OR "
            "(lease_owner IS NULL AND lease_expires_at IS NULL AND lease_epoch = 0)",
            name="sync_no_lease",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded','failed') OR completed_at IS NOT NULL",
            name="terminal_completed",
        ),
        CheckConstraint(
            "content_purged_at IS NULL OR (input_payload IS NULL AND output_payload IS NULL)",
            name="purged",
        ),
        Index(
            "uq_ai_requests_workspace_idempotency",
            "workspace_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND workspace_id IS NOT NULL"),
        ),
        Index(
            "uq_ai_requests_system_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("scope = 'system' AND idempotency_key IS NOT NULL"),
        ),
        Index("ix_ai_requests_workspace_id_id", "workspace_id", "id"),
        Index(
            "ix_ai_requests_running_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'running' AND mode = 'async'"),
        ),
        Index(
            "ix_ai_requests_sync_running",
            "started_at",
            postgresql_where=text("status = 'running' AND mode = 'sync'"),
        ),
        Index(
            "ix_ai_requests_queued_at",
            "queued_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ix_ai_requests_purge_candidates",
            "completed_at",
            postgresql_where=text(
                "content_purged_at IS NULL AND status IN ('succeeded','failed') "
                "AND (input_payload IS NOT NULL OR output_payload IS NOT NULL)"
            ),
        ),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_new_id)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_name: Mapped[str | None] = mapped_column(Text)
    output_schema_version: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    request_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))
    input_payload: Mapped[Any | None] = mapped_column(JSONB)
    output_payload: Mapped[Any | None] = mapped_column(JSONB)
    content_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_epoch: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    routing_version: Mapped[str | None] = mapped_column(Text)
    input_units: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    output_units: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    cost_micro_usd: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    correlation_request_id: Mapped[str] = mapped_column(Text, nullable=False)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiUsageRecord(Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        UniqueConstraint("request_id", "attempt_no", name="uq_ai_usage_records_request_attempt"),
        CheckConstraint(SCOPE_WORKSPACE_RULE, name="scope_workspace"),
        CheckConstraint("status IN ('reserved','succeeded','failed','abandoned')", name="status"),
        CheckConstraint("call_kind IN ('generation','repair','embedding')", name="call_kind"),
        CheckConstraint("billing_mode IN ('free_tier','paid')", name="billing_mode"),
        CheckConstraint(
            "reserved_micro_usd >= 0 AND cost_micro_usd >= 0 "
            "AND COALESCE(input_units,0) >= 0 AND COALESCE(output_units,0) >= 0",
            name="nonneg",
        ),
        CheckConstraint("status = 'reserved' OR finished_at IS NOT NULL", name="settled"),
        Index("ix_ai_usage_records_workspace_started", "workspace_id", "started_at"),
        Index(
            "ix_ai_usage_records_scope_started",
            "scope",
            "started_at",
            postgresql_where=text("scope = 'system'"),
        ),
        Index(
            "ix_ai_usage_records_reserved",
            "started_at",
            postgresql_where=text("status = 'reserved'"),
        ),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_new_id)
    request_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ai_requests.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    task: Mapped[str] = mapped_column(Text, nullable=False)
    call_kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_version: Mapped[str] = mapped_column(Text, nullable=False)
    price_version: Mapped[str] = mapped_column(Text, nullable=False)
    billing_mode: Mapped[str] = mapped_column(Text, nullable=False)
    routing_version: Mapped[str] = mapped_column(Text, nullable=False)
    route_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_snapshot: Mapped[Any] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    input_units: Mapped[int | None] = mapped_column(BigInteger)
    output_units: Mapped[int | None] = mapped_column(BigInteger)
    reserved_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_micro_usd: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    schema_valid: Mapped[bool | None] = mapped_column(Boolean)
    validation_error_count: Mapped[int | None] = mapped_column(Integer)
    validation_error_types: Mapped[Any | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiBudgetPeriod(Base):
    __tablename__ = "ai_budget_periods"
    __table_args__ = (
        CheckConstraint(SCOPE_WORKSPACE_RULE, name="scope_workspace"),
        CheckConstraint(
            "limit_micro_usd >= 0 AND reserved_micro_usd >= 0 AND spent_micro_usd >= 0",
            name="nonneg",
        ),
        Index(
            "uq_ai_budget_periods_workspace_period",
            "workspace_id",
            "period_start",
            unique=True,
            postgresql_where=text("scope = 'workspace'"),
        ),
        Index(
            "uq_ai_budget_periods_system_period",
            "period_start",
            unique=True,
            postgresql_where=text("scope = 'system'"),
        ),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=_new_id)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    limit_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_micro_usd: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    spent_micro_usd: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    warning_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exhausted_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconcile_mismatch_bucket: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
