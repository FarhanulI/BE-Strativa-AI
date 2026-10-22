from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core import SystemClock, UUID7Factory
from app.db_migrations import TENANT_SCOPED, Base

PROFILE_TYPES = (
    "creator",
    "business",
    "personal_brand",
    "expert",
    "coach",
    "startup",
    "local_business",
    "ecommerce_brand",
)


class ContentProfile(Base):
    __tablename__ = "content_profiles"
    __table_args__ = (
        UniqueConstraint("id", "workspace_id", name="uq_content_profiles_id_workspace"),
        CheckConstraint(
            "type IN ('creator', 'business', 'personal_brand', 'expert', 'coach', "
            "'startup', 'local_business', 'ecommerce_brand')",
            name="valid_type",
        ),
        CheckConstraint(
            "maturity_stage IN ('cold_start', 'early_growth', 'mature')",
            name="valid_maturity_stage",
        ),
        CheckConstraint("verified_performance_count >= 0", name="nonnegative_performance_count"),
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint("jsonb_typeof(goals) = 'array'", name="goals_array"),
        Index("ix_content_profiles_workspace_archived", "workspace_id", "archived_at"),
        Index("ix_content_profiles_workspace_type", "workspace_id", "type"),
        Index("ix_content_profiles_topics_gin", "topics", postgresql_using="gin"),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=lambda: UUID7Factory(SystemClock()).new()
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    positioning: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    topics: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    expertise: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    goals: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    maturity_stage: Mapped[str] = mapped_column(
        String(24), nullable=False, default="cold_start", server_default="cold_start"
    )
    verified_performance_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=lambda: SystemClock().now(),
    )


class ProfileBusinessContext(Base):
    __tablename__ = "profile_business_contexts"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(commercial_objectives) = 'array'", name="objectives_array"
        ),
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["content_profiles.id", "content_profiles.workspace_id"],
            name="fk_profile_business_contexts_profile_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_profile_business_contexts_workspace", "workspace_id"),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    commercial_objectives: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=lambda: SystemClock().now(),
    )


class ProfileProduct(Base):
    __tablename__ = "profile_products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["content_profiles.id", "content_profiles.workspace_id"],
            name="fk_profile_products_profile_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_profile_products_workspace_profile_id", "workspace_id", "profile_id", "id"),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=lambda: UUID7Factory(SystemClock()).new()
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    item_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=lambda: SystemClock().now(),
    )


class ProfileServiceItem(Base):
    __tablename__ = "profile_services"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["content_profiles.id", "content_profiles.workspace_id"],
            name="fk_profile_services_profile_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_profile_services_workspace_profile_id", "workspace_id", "profile_id", "id"),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=lambda: UUID7Factory(SystemClock()).new()
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    item_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=lambda: SystemClock().now(),
    )


class ProfileOffer(Base):
    __tablename__ = "profile_offers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["profile_id", "workspace_id"],
            ["content_profiles.id", "content_profiles.workspace_id"],
            name="fk_profile_offers_profile_workspace",
            ondelete="CASCADE",
        ),
        Index("ix_profile_offers_workspace_profile_id", "workspace_id", "profile_id", "id"),
        {"info": {"tenant_scope": TENANT_SCOPED}},
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=lambda: UUID7Factory(SystemClock()).new()
    )
    workspace_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    item_metadata: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=lambda: SystemClock().now(),
    )