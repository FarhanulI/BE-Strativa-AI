from __future__ import annotations

import secrets
from datetime import datetime
from typing import NewType
from uuid import UUID

from app.core.clock import Clock

_MAX_TIMESTAMP_MS = (1 << 48) - 1
_RAND_B_MASK = (1 << 62) - 1
UUID7 = NewType("UUID7", UUID)


def new_uuid7(now: datetime) -> UUID7:
    """Create an RFC 9562 UUIDv7 using the supplied timezone-aware time."""
    if now.tzinfo is None:
        raise ValueError("UUIDv7 timestamp must be timezone-aware")

    timestamp_ms = int(now.timestamp() * 1000)
    if not 0 <= timestamp_ms <= _MAX_TIMESTAMP_MS:
        raise ValueError("UUIDv7 timestamp is outside the supported range")

    random_bits = secrets.randbits(74)
    rand_a = random_bits >> 62
    rand_b = random_bits & _RAND_B_MASK
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (rand_a << 64)
        | (0b10 << 62)
        | rand_b
    )
    return UUID7(UUID(int=value))


class UUID7Factory:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def new(self) -> UUID7:
        return new_uuid7(self._clock.now())