"""The injectable clock. Engine code receives a Clock; it never reads the system clock itself."""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    """A source of the current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


def utc_now(clock: Clock) -> datetime:
    """Read the clock and insist on UTC: a naive or non-UTC reading is an error, not a guess."""
    reading = clock.now()
    if reading.tzinfo is None or reading.utcoffset() != timedelta(0):
        raise ValueError("clock must return a timezone-aware UTC datetime")
    return reading.astimezone(UTC)
