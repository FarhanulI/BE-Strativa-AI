from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.ids import UUID7


@dataclass(kw_only=True, eq=False)
class Entity:
    id: UUID7

    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return False
        assert isinstance(other, Entity)
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self), self.id))


@dataclass(kw_only=True, eq=False)
class AggregateRoot(Entity):
    pass


@dataclass(frozen=True)
class ValueObject:
    def __eq__(self, other: object) -> bool:
        if type(self) is not type(other):
            return False
        return vars(self) == vars(other)

    def __hash__(self) -> int:
        return hash((type(self), *vars(self).values()))


@dataclass(kw_only=True)
class TimestampMixin:
    created_at: datetime
    updated_at: datetime


@dataclass(kw_only=True)
class SoftDeleteMixin:
    deleted_at: datetime | None = None