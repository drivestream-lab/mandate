"""Shared pieces of the outbox tests: counting rows and a clock the test moves by hand."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from src.infra_services.postgres_service import PostgresService


async def count_rows(postgres: PostgresService, table: str, where: str = "true") -> int:
    """Rows of a table, read in a fresh session."""
    async with postgres.get_session() as session:
        result = await session.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"))
        return int(result.scalar_one())


class ManualClock:
    """A clock that only moves when told to."""

    def __init__(self) -> None:
        self._now = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, by: timedelta) -> None:
        self._now += by
