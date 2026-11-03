from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory

import app.ai_platform as ai_platform
from app.ai_platform.models import AiBudgetPeriod, AiRequest, AiUsageRecord
from app.db_migrations import TENANT_SCOPED, Base, validate_tenant_scope

AI_TABLES = ("ai_requests", "ai_usage_records", "ai_budget_periods")


def test_ai_tables_are_registered_and_tenant_scoped() -> None:
    assert set(AI_TABLES) <= set(Base.metadata.tables)
    validate_tenant_scope()
    for model in (AiRequest, AiUsageRecord, AiBudgetPeriod):
        assert model.__table__.info["tenant_scope"] == TENANT_SCOPED
        assert model.__table__.metadata is Base.metadata


def test_workspace_id_is_nullable_on_every_ai_table() -> None:
    for name in AI_TABLES:
        assert Base.metadata.tables[name].c.workspace_id.nullable is True


def test_money_columns_are_bigint_micro_usd() -> None:
    money = {
        "ai_requests": ["cost_micro_usd"],
        "ai_usage_records": ["reserved_micro_usd", "cost_micro_usd"],
        "ai_budget_periods": ["limit_micro_usd", "reserved_micro_usd", "spent_micro_usd"],
    }
    for table, columns in money.items():
        for column in columns:
            assert Base.metadata.tables[table].c[column].type.__class__.__name__ == "BigInteger"


def test_package_exports_nothing_public_yet() -> None:
    assert ai_platform.__all__ == []


def test_alembic_has_a_single_head_after_profile() -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0008_ai_platform"]
    revision = script.get_revision("0008_ai_platform")
    assert revision is not None
    assert revision.down_revision == "0007_profile"
