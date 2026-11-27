"""The one real clock: reads the system time. Engine code gets it by injection, never imports it."""

from datetime import UTC, datetime


class SystemClockService:
    """A Clock backed by the system time, in UTC."""

    def now(self) -> datetime:
        """Return the current system time as a timezone-aware UTC datetime."""
        return datetime.now(UTC)
