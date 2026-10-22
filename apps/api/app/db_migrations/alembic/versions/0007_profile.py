"""Create tenant-scoped content profiles and optional business context."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_profile"
down_revision = "0006_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("positioning", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "topics",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "expertise",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "goals",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "maturity_stage",
            sa.String(length=24),
            server_default="cold_start",
            nullable=False,
        ),
        sa.Column("verified_performance_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('creator', 'business', 'personal_brand', 'expert', 'coach', "
            "'startup', 'local_business', 'ecommerce_brand')",
            name=op.f("ck_content_profiles_valid_type"),
        ),
        sa.CheckConstraint(
            "maturity_stage IN ('cold_start', 'early_growth', 'mature')",
            name=op.f("ck_content_profiles_valid_maturity_stage"),
        ),
        sa.CheckConstraint(
            "verified_performance_count >= 0",
            name=op.f("ck_content_profiles_nonnegative_performance_count"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_content_profiles_positive_version")),
        sa.CheckConstraint(
            "jsonb_typeof(goals) = 'array'", name=op.f("ck_content_profiles_goals_array")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_content_profiles_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_profiles")),
        sa.UniqueConstraint("id", "workspace_id", name=op.f("uq_content_profiles_id_workspace")),
        info={"tenant_scope": "tenant_scoped"},
    )
    op.create_index(
        "ix_content_profiles_workspace_archived",
        "content_profiles",
        ["workspace_id", "archived_at"],
    )
    op.create_index(
        "ix_content_profiles_workspace_type", "content_profiles", ["workspace_id", "type"]
    )
    op.create_index(
        "ix_content_profiles_topics_gin",
        "content_profiles",
        ["topics"],
        postgresql_using="gin",
    )

    op.create_table(
        "profile_business_contexts",
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column(
            "commercial_objectives",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(commercial_objectives) = 'array'",
            name=op.f("ck_profile_business_contexts_objectives_array"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["content_profiles.id", "content_profiles.workspace_id"],
            name="fk_profile_business_contexts_profile_workspace",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("profile_id", name=op.f("pk_profile_business_contexts")),
        info={"tenant_scope": "tenant_scoped"},
    )
    op.create_index(
        "ix_profile_business_contexts_workspace",
        "profile_business_contexts",
        ["workspace_id"],
    )

    for table_name in ("profile_products", "profile_services", "profile_offers"):
        op.create_table(
            table_name,
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("workspace_id", sa.Uuid(), nullable=False),
            sa.Column("profile_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.Text(), server_default="", nullable=False),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["profile_id", "workspace_id"],
                ["content_profiles.id", "content_profiles.workspace_id"],
                name=f"fk_{table_name}_profile_workspace",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table_name}")),
            info={"tenant_scope": "tenant_scoped"},
        )
        op.create_index(
            f"ix_{table_name}_workspace_profile_id",
            table_name,
            ["workspace_id", "profile_id", "id"],
        )


def downgrade() -> None:
    for table_name in ("profile_offers", "profile_services", "profile_products"):
        op.drop_index(f"ix_{table_name}_workspace_profile_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index("ix_profile_business_contexts_workspace", table_name="profile_business_contexts")
    op.drop_table("profile_business_contexts")
    op.drop_index("ix_content_profiles_topics_gin", table_name="content_profiles")
    op.drop_index("ix_content_profiles_workspace_type", table_name="content_profiles")
    op.drop_index("ix_content_profiles_workspace_archived", table_name="content_profiles")
    op.drop_table("content_profiles")
