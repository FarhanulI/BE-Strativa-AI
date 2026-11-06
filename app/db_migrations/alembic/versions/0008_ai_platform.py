"""Create the ai_platform request, usage ledger and budget tables."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_ai_platform"
down_revision = "0007_profile"
branch_labels = None
depends_on = None

SCOPE_WORKSPACE_RULE = "(scope = 'workspace') = (workspace_id IS NOT NULL)"


def _now_column(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("output_schema_name", sa.Text(), nullable=True),
        sa.Column("output_schema_version", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
        sa.Column("request_fingerprint", sa.CHAR(length=64), nullable=True),
        sa.Column("input_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_epoch", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("routing_version", sa.Text(), nullable=True),
        sa.Column("input_units", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_units", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("correlation_request_id", sa.Text(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        _now_column("updated_at"),
        sa.CheckConstraint("scope IN ('workspace','system')", name=op.f("ck_ai_requests_scope")),
        sa.CheckConstraint(SCOPE_WORKSPACE_RULE, name=op.f("ck_ai_requests_scope_workspace")),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed')",
            name=op.f("ck_ai_requests_status"),
        ),
        sa.CheckConstraint("mode IN ('sync','async')", name=op.f("ck_ai_requests_mode")),
        sa.CheckConstraint(
            "actor_type IN ('user','system','worker')", name=op.f("ck_ai_requests_actor_type")
        ),
        sa.CheckConstraint(
            "input_units >= 0 AND output_units >= 0 AND cost_micro_usd >= 0 "
            "AND attempt_count >= 0 AND lease_epoch >= 0",
            name=op.f("ck_ai_requests_nonneg"),
        ),
        sa.CheckConstraint(
            "(mode = 'async') = (idempotency_key IS NOT NULL)",
            name=op.f("ck_ai_requests_async_key"),
        ),
        sa.CheckConstraint(
            "(mode = 'async') = (request_fingerprint IS NOT NULL)",
            name=op.f("ck_ai_requests_async_fingerprint"),
        ),
        sa.CheckConstraint(
            "task = 'EMBED_TEXT' OR "
            "(output_schema_name IS NOT NULL AND output_schema_version IS NOT NULL)",
            name=op.f("ck_ai_requests_schema_name"),
        ),
        sa.CheckConstraint(
            "mode <> 'async' OR status <> 'running' OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name=op.f("ck_ai_requests_running_lease"),
        ),
        sa.CheckConstraint(
            "mode = 'async' OR "
            "(lease_owner IS NULL AND lease_expires_at IS NULL AND lease_epoch = 0)",
            name=op.f("ck_ai_requests_sync_no_lease"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('succeeded','failed') OR completed_at IS NOT NULL",
            name=op.f("ck_ai_requests_terminal_completed"),
        ),
        sa.CheckConstraint(
            "content_purged_at IS NULL OR (input_payload IS NULL AND output_payload IS NULL)",
            name=op.f("ck_ai_requests_purged"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ai_requests_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name=op.f("fk_ai_requests_requested_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_requests")),
        info={"tenant_scope": "tenant_scoped"},
    )
    op.create_index(
        "uq_ai_requests_workspace_idempotency",
        "ai_requests",
        ["workspace_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL AND workspace_id IS NOT NULL"),
    )
    op.create_index(
        "uq_ai_requests_system_idempotency",
        "ai_requests",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("scope = 'system' AND idempotency_key IS NOT NULL"),
    )
    op.create_index("ix_ai_requests_workspace_id_id", "ai_requests", ["workspace_id", "id"])
    op.create_index(
        "ix_ai_requests_running_lease",
        "ai_requests",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running' AND mode = 'async'"),
    )
    op.create_index(
        "ix_ai_requests_sync_running",
        "ai_requests",
        ["started_at"],
        postgresql_where=sa.text("status = 'running' AND mode = 'sync'"),
    )
    op.create_index(
        "ix_ai_requests_queued_at",
        "ai_requests",
        ["queued_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_ai_requests_purge_candidates",
        "ai_requests",
        ["completed_at"],
        postgresql_where=sa.text(
            "content_purged_at IS NULL AND status IN ('succeeded','failed') "
            "AND (input_payload IS NOT NULL OR output_payload IS NOT NULL)"
        ),
    )

    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("call_kind", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("catalog_version", sa.Text(), nullable=False),
        sa.Column("price_version", sa.Text(), nullable=False),
        sa.Column("billing_mode", sa.Text(), nullable=False),
        sa.Column("routing_version", sa.Text(), nullable=False),
        sa.Column("route_rank", sa.Integer(), nullable=False),
        sa.Column(
            "candidate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("finish_reason", sa.Text(), nullable=True),
        sa.Column("input_units", sa.BigInteger(), nullable=True),
        sa.Column("output_units", sa.BigInteger(), nullable=True),
        sa.Column("reserved_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("cost_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("schema_valid", sa.Boolean(), nullable=True),
        sa.Column("validation_error_count", sa.Integer(), nullable=True),
        sa.Column(
            "validation_error_types", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.CheckConstraint(
            "scope IN ('workspace','system')", name=op.f("ck_ai_usage_records_scope")
        ),
        sa.CheckConstraint(
            SCOPE_WORKSPACE_RULE, name=op.f("ck_ai_usage_records_scope_workspace")
        ),
        sa.CheckConstraint(
            "status IN ('reserved','succeeded','failed','abandoned')",
            name=op.f("ck_ai_usage_records_status"),
        ),
        sa.CheckConstraint(
            "call_kind IN ('generation','repair','embedding')",
            name=op.f("ck_ai_usage_records_call_kind"),
        ),
        sa.CheckConstraint(
            "billing_mode IN ('free_tier','paid')",
            name=op.f("ck_ai_usage_records_billing_mode"),
        ),
        sa.CheckConstraint(
            "reserved_micro_usd >= 0 AND cost_micro_usd >= 0 "
            "AND COALESCE(input_units,0) >= 0 AND COALESCE(output_units,0) >= 0",
            name=op.f("ck_ai_usage_records_nonneg"),
        ),
        sa.CheckConstraint(
            "status = 'reserved' OR finished_at IS NOT NULL",
            name=op.f("ck_ai_usage_records_settled"),
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["ai_requests.id"],
            name=op.f("fk_ai_usage_records_request_id_ai_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ai_usage_records_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_usage_records")),
        sa.UniqueConstraint(
            "request_id", "attempt_no", name=op.f("uq_ai_usage_records_request_attempt")
        ),
        info={"tenant_scope": "tenant_scoped"},
    )
    op.create_index(
        "ix_ai_usage_records_workspace_started",
        "ai_usage_records",
        ["workspace_id", "started_at"],
    )
    op.create_index(
        "ix_ai_usage_records_scope_started",
        "ai_usage_records",
        ["scope", "started_at"],
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "ix_ai_usage_records_reserved",
        "ai_usage_records",
        ["started_at"],
        postgresql_where=sa.text("status = 'reserved'"),
    )

    op.create_table(
        "ai_budget_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("limit_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column("reserved_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("spent_micro_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("warning_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exhausted_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconcile_mismatch_bucket", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        _now_column("updated_at"),
        sa.CheckConstraint(
            "scope IN ('workspace','system')", name=op.f("ck_ai_budget_periods_scope")
        ),
        sa.CheckConstraint(
            SCOPE_WORKSPACE_RULE, name=op.f("ck_ai_budget_periods_scope_workspace")
        ),
        sa.CheckConstraint(
            "limit_micro_usd >= 0 AND reserved_micro_usd >= 0 AND spent_micro_usd >= 0",
            name=op.f("ck_ai_budget_periods_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_ai_budget_periods_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_budget_periods")),
        info={"tenant_scope": "tenant_scoped"},
    )
    op.create_index(
        "uq_ai_budget_periods_workspace_period",
        "ai_budget_periods",
        ["workspace_id", "period_start"],
        unique=True,
        postgresql_where=sa.text("scope = 'workspace'"),
    )
    op.create_index(
        "uq_ai_budget_periods_system_period",
        "ai_budget_periods",
        ["period_start"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ai_budget_periods_system_period", table_name="ai_budget_periods")
    op.drop_index("uq_ai_budget_periods_workspace_period", table_name="ai_budget_periods")
    op.drop_table("ai_budget_periods")

    op.drop_index("ix_ai_usage_records_reserved", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_records_scope_started", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_records_workspace_started", table_name="ai_usage_records")
    op.drop_table("ai_usage_records")

    op.drop_index("ix_ai_requests_purge_candidates", table_name="ai_requests")
    op.drop_index("ix_ai_requests_queued_at", table_name="ai_requests")
    op.drop_index("ix_ai_requests_sync_running", table_name="ai_requests")
    op.drop_index("ix_ai_requests_running_lease", table_name="ai_requests")
    op.drop_index("ix_ai_requests_workspace_id_id", table_name="ai_requests")
    op.drop_index("uq_ai_requests_system_idempotency", table_name="ai_requests")
    op.drop_index("uq_ai_requests_workspace_idempotency", table_name="ai_requests")
    op.drop_table("ai_requests")
