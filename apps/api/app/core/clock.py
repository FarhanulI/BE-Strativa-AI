from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FakeClock:
    current_time: datetime

    def __post_init__(self) -> None:
        if self.current_time.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")

    def now(self) -> datetime:
        return self.current_time

    def set(self, value: datetime) -> None:
        if value.tzinfo is None:
            raise ValueError("FakeClock requires a timezone-aware datetime")
        self.current_time = value

    def advance(self, amount: timedelta) -> datetime:
        self.current_time += amount
        return self.current_time