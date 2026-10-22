from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.pool import NullPool

from app.auth import AuthSession, User
from app.core import Settings
from app.db_migrations import (
    Base,
    build_async_engine,
    validate_migration_target,
    validate_tenant_scope,
)
from app.events_outbox import OutboxEvent, ProcessedEvent
from app.observability_audit import AuditLog
from app.profile import (
    ContentProfile,
    ProfileBusinessContext,
    ProfileOffer,
    ProfileProduct,
    ProfileServiceItem,
)
from app.workspace import Workspace, WorkspaceInvitation, WorkspaceMember

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = Settings()
database_url = validate_migration_target(
    settings,
    allow_prod=bool(config.attributes.get("allow_prod", False)),
)
target_metadata = Base.metadata
for model in (
    OutboxEvent,
    ProcessedEvent,
    AuditLog,
    AuthSession,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    ContentProfile,
    ProfileBusinessContext,
    ProfileProduct,
    ProfileServiceItem,
    ProfileOffer,
):
    if model.__table__.metadata is not target_metadata:
        raise RuntimeError("Foundation model is not registered with the shared metadata")
validate_tenant_scope(target_metadata)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = build_async_engine(
        database_url,
        pooled=False,
        engine_options={"poolclass": NullPool},
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())