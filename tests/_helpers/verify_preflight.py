"""Verify preflight: checks infra is up before running verify tests."""

import asyncio
import sys
from collections.abc import Awaitable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from redis.asyncio import Redis

from src.configs.postgres_settings import PostgresSettings
from src.configs.redis_settings import RedisSettings


class _Pingable(Protocol):
    def ping(self) -> Awaitable[bool]: ...


class _Closable(Protocol):
    def aclose(self) -> Awaitable[None]: ...


async def _ping(client: _Pingable) -> None:
    await client.ping()


async def _close(client: _Closable) -> None:
    await client.aclose()


async def check_postgres() -> None:
    s = PostgresSettings.get_instance()
    engine = create_async_engine(s.sqlalchemy_database_uri)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    print("ok: postgres reachable")


async def check_redis() -> None:
    s = RedisSettings.get_instance()
    r = Redis(
        host=s.host,
        port=s.port,
        db=s.db,
        password=s.password.get_secret_value() if s.password else None,
        ssl=s.use_ssl,
    )
    await _ping(r)
    await _close(r)
    print("ok: redis reachable")


async def main() -> None:
    results = await asyncio.gather(check_postgres(), check_redis(), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]
    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
