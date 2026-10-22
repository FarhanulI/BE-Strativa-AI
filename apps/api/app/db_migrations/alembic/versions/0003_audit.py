"""Create append-only audit storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_audit"
down_revision = "0002_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=200), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(op.f("ix_audit_log_occurred_at"), "audit_log", ["occurred_at"])
    op.create_index(
        "ix_audit_log_workspace_occurred_at", "audit_log", ["workspace_id", "occurred_at"]
    )
    op.create_index("ix_audit_log_actor_occurred_at", "audit_log", ["actor_id", "occurred_at"])
    op.create_index(
        "ix_audit_log_resource_occurred_at",
        "audit_log",
        ["resource_type", "resource_id", "occurred_at"],
    )
    op.execute(
        """CREATE FUNCTION reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'audit_log is append-only';
        END; $$"""
    )
    op.execute(
        """CREATE TRIGGER audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation()"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS reject_audit_mutation()")
    op.drop_table("audit_log")