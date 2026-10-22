from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.db_migrations import build_async_engine, normalize_postgres_url
from app.db_migrations.base import Base, validate_tenant_scope
from app.events_outbox import OutboxEvent, ProcessedEvent
from app.observability_audit import AuditLog


def test_normalize_neon_postgres_url_and_tls_parameters() -> None:
    url, tls_requested = normalize_postgres_url(
        "postgresql://user:secret@host/db?sslmode=require&channel_binding=require&application_name=studio"
    )

    assert url == "postgresql+asyncpg://user:secret@host/db?application_name=studio"
    assert tls_requested


def test_normalize_rejects_non_postgres_url() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_postgres_url("sqlite:///local.db")


def test_pooled_engine_disables_statement_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = Mock(return_value=object())
    monkeypatch.setattr("app.db_migrations.engine.create_async_engine", factory)

    build_async_engine("postgresql://user:secret@host/db?sslmode=require", pooled=True)

    args, options = factory.call_args
    assert args == ("postgresql+asyncpg://user:secret@host/db",)
    assert options["pool_pre_ping"] is True
    assert "prepared_statement_cache_size" not in options
    assert options["connect_args"] == {
        "timeout": 30,
        "ssl": "require",
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }


def test_direct_engine_keeps_driver_statement_cache_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = Mock(return_value=object())
    monkeypatch.setattr("app.db_migrations.engine.create_async_engine", factory)

    build_async_engine("postgres://user:secret@host/db", pooled=False)

    _, options = factory.call_args
    assert "prepared_statement_cache_size" not in options
    assert options["connect_args"] == {"timeout": 30}


def test_metadata_requires_explicit_tenant_classification() -> None:
    metadata = Base.metadata.__class__()
    metadata.info["tenant_scope"] = "global"
    from sqlalchemy import Table

    Table("unclassified", metadata)
    with pytest.raises(ValueError, match="unclassified"):
        validate_tenant_scope(metadata)


def test_all_registered_foundation_tables_have_tenant_scope() -> None:
    assert {"outbox_events", "processed_events", "audit_log"} <= set(Base.metadata.tables)
    validate_tenant_scope()
    assert OutboxEvent.__table__.info["tenant_scope"] == "global"
    assert ProcessedEvent.__table__.info["tenant_scope"] == "global"
    assert AuditLog.__table__.info["tenant_scope"] == "global"


@pytest.mark.asyncio
async def test_pooled_engine_constructs_without_mocking_sqlalchemy() -> None:
    engine = build_async_engine("postgresql://user@localhost/db", pooled=True)
    await engine.dispose()