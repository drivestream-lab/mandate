"""Fixtures for tests that need a real Postgres: a migrated throwaway database per test.

Each test run creates its own throwaway database on the server named by the environment,
migrates it with the repository's migrations as the superuser, and drops it afterwards, so it
never touches the entries any other test left. Settings come from the environment:

    MANDATE_DB_HOST, MANDATE_DB_PORT,
    MANDATE_DB_ADMIN_USER (default postgres), MANDATE_DB_ADMIN_PASSWORD,
    MANDATE_DB_APP_PASSWORD

For `make deploy` the host and port are the stack's published Postgres and all passwords are
the stack's throwaway ones. A missing setting fails the test; it never skips.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from src.configs.base_settings import BaseSettings
from src.database.postgres.connection_manager import PostgresConnectionManager
from src.infra_services.postgres_service import PostgresService
from tests._helpers.database_settings import setting

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(name="database")
def throwaway_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[str]:
    host, port = setting("MANDATE_DB_HOST"), setting("MANDATE_DB_PORT")
    admin, admin_password = setting("MANDATE_DB_ADMIN_USER", "postgres"), setting(
        "MANDATE_DB_ADMIN_PASSWORD"
    )
    name = f"test_{uuid.uuid4().hex[:12]}"
    url = URL.create(
        "postgresql+psycopg2",
        username=admin,
        password=admin_password,
        host=host,
        port=int(port),
        database="postgres",
    )
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin_file = tmp_path / "admin-password"
    admin_file.write_text(admin_password)
    app_file = tmp_path / "app-password"
    app_file.write_text(setting("MANDATE_DB_APP_PASSWORD"))
    migrate_env = {
        **os.environ,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port,
        "POSTGRES_USER": admin,
        "POSTGRES_PASSWORD_FILE": str(admin_file),
        "POSTGRES_MIGRATION_USER": admin,
        "POSTGRES_MIGRATION_PASSWORD_FILE": str(admin_file),
        "POSTGRES_DB": name,
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(_ROOT / "postgres_migrations" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=_ROOT,
        env=migrate_env,
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("POSTGRES_HOST", host)
    monkeypatch.setenv("POSTGRES_PORT", port)
    monkeypatch.setenv("POSTGRES_USER", "mandate_app")
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(app_file))
    monkeypatch.setenv("POSTGRES_DB", name)
    BaseSettings.clear_instances()
    yield name
    BaseSettings.clear_instances()
    with engine.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    engine.dispose()


@pytest_asyncio.fixture(name="postgres")
async def app_postgres(database: str) -> AsyncIterator[PostgresService]:
    service = PostgresService(PostgresConnectionManager())
    await service.initialize()
    yield service
    await service.close()
