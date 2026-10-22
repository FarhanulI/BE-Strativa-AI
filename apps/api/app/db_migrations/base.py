from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

TENANT_SCOPED = "tenant_scoped"
GLOBAL = "global"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def validate_tenant_scope(metadata: MetaData = Base.metadata) -> None:
    invalid = [
        table.name
        for table in metadata.tables.values()
        if table.info.get("tenant_scope") not in (TENANT_SCOPED, GLOBAL)
    ]
    if invalid:
        names = ", ".join(sorted(invalid))
        raise ValueError(f"Tables missing valid tenant_scope metadata: {names}")