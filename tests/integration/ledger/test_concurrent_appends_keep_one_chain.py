"""Appends against a real Postgres: concurrent writers keep one chain, and a forked write fails.

Each test run creates its own throwaway database on the server named by the environment,
migrates it with the repository's migrations as the superuser, and drops it afterwards, so it
never touches the entries any other test left. Settings come from the environment:

    MANDATE_DB_HOST, MANDATE_DB_PORT,
    MANDATE_DB_ADMIN_USER (default postgres), MANDATE_DB_ADMIN_PASSWORD,
    MANDATE_DB_APP_PASSWORD

For `make deploy` the host and port are the stack's published Postgres and all passwords are
the stack's throwaway ones. A missing setting fails the test; it never skips.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from src.business_services.ledger.ledger_append_service import (
    CorrectedEntryNotFoundError,
    LedgerAppendService,
)
from src.configs.base_settings import BaseSettings
from src.database.postgres.connection_manager import PostgresConnectionManager
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.infra_services.postgres_service import PostgresService
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import (
    ChainAnchor,
    CorrectionRecord,
    DecisionOption,
    DecisionRecord,
    RungType,
    StoredLedgerEntry,
)

_ROOT = Path(__file__).resolve().parents[3]
_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="review", version="2"),),
    skills=(NamedVersion(name="spec-read", version="5"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)


def _setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default or "")
    if not value:
        pytest.fail(f"{name} is not set; see this file's docstring for the settings it needs")
    return value


def _decision(n: int) -> DecisionRecord:
    return DecisionRecord(
        actor="nikd10x",
        role="decision owner",
        rung=RungType.L0,
        options_offered=(DecisionOption(option_id="approve", description="Merge it"),),
        choice="approve",
        reasons=(f"reason {n}",),
        evidence=(),
        target_version=f"version-{n}",
        workflow_version="workflow-4",
        model_version="model-7",
        decided_at=datetime(2026, 11, 27, 12, 0, tzinfo=UTC),
    )


@pytest.fixture(name="database")
def throwaway_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    host, port = _setting("MANDATE_DB_HOST"), _setting("MANDATE_DB_PORT")
    admin, admin_password = _setting("MANDATE_DB_ADMIN_USER", "postgres"), _setting(
        "MANDATE_DB_ADMIN_PASSWORD"
    )
    name = f"ledger_{uuid.uuid4().hex[:12]}"
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
    migrate_env = {
        **os.environ,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port,
        "POSTGRES_USER": admin,
        "POSTGRES_PASSWORD": admin_password,
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
    monkeypatch.setenv("POSTGRES_PASSWORD", _setting("MANDATE_DB_APP_PASSWORD"))
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


@pytest.mark.req("REQ-55")
async def test_concurrent_appends_make_one_unforked_chain(postgres: PostgresService) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    # Warm the connection pool, so the writers really overlap instead of queueing to connect.
    await asyncio.gather(*(service.verify() for _ in range(15)))
    stored: list[StoredLedgerEntry] = []
    for round_number in range(4):
        stored += await asyncio.gather(
            *(service.append_decision(_decision(round_number * 5 + n), _STAMP) for n in range(5))
        )
    assert len({entry.entry_hash for entry in stored}) == 20
    result = await service.verify()
    assert result.entries_checked == 20
    assert result.is_intact
    head = max(stored, key=lambda entry: entry.sequence).entry_hash
    assert head is not None
    assert (await service.verify(ChainAnchor(head_hash=head))).is_intact


@pytest.mark.req("REQ-55")
async def test_a_writer_that_skips_the_lock_cannot_fork_the_chain(
    postgres: PostgresService,
) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    first = await service.append_decision(_decision(1), _STAMP)
    await service.append_decision(_decision(2), _STAMP)
    # A stale writer that read the head before the second append and links to the first entry.
    async with postgres.transaction() as session:
        with pytest.raises(DBAPIError) as refusal:
            await session.execute(
                text(
                    "INSERT INTO ledger.entries "
                    "(entry_id, entry_type, payload, previous_hash, entry_hash) "
                    "VALUES (:id, 'decision', CAST('{}' AS jsonb), :previous, :own)"
                ),
                {"id": uuid.uuid4(), "previous": first.entry_hash, "own": "f" * 64},
            )
    assert "entries_previous_hash_key" in str(refusal.value)
    assert (await service.verify()).is_intact


@pytest.mark.req("REQ-55")
async def test_a_correction_is_a_new_entry_and_the_original_stays(
    postgres: PostgresService,
) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    original = await service.append_decision(_decision(1), _STAMP)
    assert original.entry_hash is not None
    correction = await service.append_correction(
        CorrectionRecord(
            corrects_entry_hash=original.entry_hash,
            actor="nikd10x",
            reason="wrong target",
            corrected_decision=_decision(2),
        ),
        _STAMP,
    )
    assert correction.payload["corrects_entry_hash"] == original.entry_hash
    assert correction.previous_hash == original.entry_hash
    repository = LedgerRepository()
    async with postgres.get_session() as session:
        unchanged = await repository.get_by_hash(session, original.entry_hash)
    assert unchanged == original
    assert (await service.verify()).is_intact


@pytest.mark.req("REQ-55")
async def test_a_correction_of_an_unknown_entry_is_refused(postgres: PostgresService) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    with pytest.raises(CorrectedEntryNotFoundError):
        await service.append_correction(
            CorrectionRecord(
                corrects_entry_hash="c" * 64,
                actor="nikd10x",
                reason="r",
                corrected_decision=_decision(1),
            ),
            _STAMP,
        )
    assert (await service.verify()).entries_checked == 0


@pytest.mark.req("REQ-55")
async def test_an_entry_edited_by_the_owner_is_found(
    postgres: PostgresService, database: str
) -> None:
    service = LedgerAppendService(postgres, LedgerRepository())
    last = None
    for n in range(3):
        last = await service.append_decision(_decision(n), _STAMP)
    assert last is not None
    head = last.entry_hash
    assert head is not None
    url = URL.create(
        "postgresql+psycopg2",
        username=_setting("MANDATE_DB_ADMIN_USER", "postgres"),
        password=_setting("MANDATE_DB_ADMIN_PASSWORD"),
        host=_setting("MANDATE_DB_HOST"),
        port=int(_setting("MANDATE_DB_PORT")),
        database=database,
    )
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(
            text("ALTER TABLE ledger.entries DISABLE TRIGGER entries_reject_rewrite")
        )
        connection.execute(
            text(
                "UPDATE ledger.entries SET payload = jsonb_set(payload, "
                "'{content,actor}', '\"someone else\"') WHERE sequence = "
                "(SELECT min(sequence) FROM ledger.entries)"
            )
        )
    engine.dispose()
    result = await service.verify(ChainAnchor(head_hash=head))
    assert not result.is_intact
