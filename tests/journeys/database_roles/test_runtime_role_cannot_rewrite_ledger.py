"""Journey: the runtime role cannot rewrite the ledger, and neither can the owner by accident.

Runs against a real Postgres that already has the migration applied: the one `make deploy`
starts. Never point it at the lab: every run appends probe entries, and ledger entries cannot
be removed. Connection settings come from the environment, never from the repo:

    MANDATE_DB_HOST, MANDATE_DB_PORT, MANDATE_DB_NAME,
    MANDATE_DB_OWNER_PASSWORD, MANDATE_DB_APP_PASSWORD

For `make deploy`, the host and port are the stack's published Postgres
(`docker compose -p <project> port postgres 5432`), the database is ds_mandate_db and both
passwords are the stack's throwaway ones. A missing setting fails the test; it never skips.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import DBAPIError

OWNER_ROLE = "mandate_owner"
APP_ROLE = "mandate_app"
CAPABILITY_SCHEMAS = {
    "ledger",
    "runner",
    "gates",
    "release",
    "programmes",
    "policy",
    "outbox",
    "inbound",
}
PROBE_TYPE = "journey_probe"


def _setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"{name} is not set; see this file's docstring for the settings it needs")
    return value


def _engine(role: str, password_setting: str) -> Engine:
    url = URL.create(
        "postgresql+psycopg2",
        username=role,
        password=_setting(password_setting),
        host=_setting("MANDATE_DB_HOST"),
        port=int(_setting("MANDATE_DB_PORT")),
        database=_setting("MANDATE_DB_NAME"),
    )
    return create_engine(url, isolation_level="AUTOCOMMIT")


@pytest.fixture(name="app")
def app_connection() -> Iterator[Connection]:
    engine = _engine(APP_ROLE, "MANDATE_DB_APP_PASSWORD")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture(name="owner")
def owner_connection() -> Iterator[Connection]:
    engine = _engine(OWNER_ROLE, "MANDATE_DB_OWNER_PASSWORD")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture(name="entry_id")
def probe_entry(app: Connection) -> uuid.UUID:
    """One entry written the way the runtime writes them: as mandate_app."""
    entry_id = uuid.uuid4()
    app.execute(
        text(
            "INSERT INTO ledger.entries (entry_id, entry_type, payload) "
            "VALUES (:entry_id, :entry_type, CAST('{\"n\": 1}' AS jsonb))"
        ),
        {"entry_id": entry_id, "entry_type": PROBE_TYPE},
    )
    return entry_id


def _payload(connection: Connection, entry_id: uuid.UUID) -> str | None:
    row = connection.execute(
        text("SELECT payload::text FROM ledger.entries WHERE entry_id = :entry_id"),
        {"entry_id": entry_id},
    ).first()
    return None if row is None else str(row[0])


def _refused(connection: Connection, statement: str, entry_id: uuid.UUID) -> str:
    """Run a statement that Postgres must refuse; return its error text."""
    with pytest.raises(DBAPIError) as refusal:
        connection.execute(text(statement), {"entry_id": entry_id})
    return str(refusal.value)


_UPDATE = (
    "UPDATE ledger.entries SET payload = CAST('{\"n\": 2}' AS jsonb) WHERE entry_id = :entry_id"
)
_DELETE = "DELETE FROM ledger.entries WHERE entry_id = :entry_id"
_TRUNCATE = "TRUNCATE ledger.entries"


@pytest.mark.req("REQ-55")
def test_each_capability_has_a_schema_whose_tables_the_owner_owns(owner: Connection) -> None:
    schemas = {
        row[0]
        for row in owner.execute(text("SELECT schema_name FROM information_schema.schemata")).all()
    }
    assert CAPABILITY_SCHEMAS <= schemas

    tables = owner.execute(
        text(
            "SELECT schemaname, tablename, tableowner FROM pg_tables "
            "WHERE schemaname = ANY(:schemas)"
        ),
        {"schemas": sorted(CAPABILITY_SCHEMAS)},
    ).all()
    assert {"entries", "work_items", "gates", "messages"} <= {row[1] for row in tables}
    assert {row[2] for row in tables} == {OWNER_ROLE}


@pytest.mark.req("REQ-55")
def test_runtime_role_can_only_insert_and_select_on_the_ledger(
    app: Connection, owner: Connection
) -> None:
    privileges = {
        row[0]
        for row in owner.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE table_schema = 'ledger' AND table_name = 'entries' "
                "AND grantee = :role"
            ),
            {"role": APP_ROLE},
        ).all()
    }
    assert privileges == {"SELECT"}
    insertable = {
        row[0]
        for row in owner.execute(
            text(
                "SELECT column_name FROM information_schema.column_privileges "
                "WHERE table_schema = 'ledger' AND table_name = 'entries' "
                "AND grantee = :role AND privilege_type = 'INSERT'"
            ),
            {"role": APP_ROLE},
        ).all()
    }
    assert insertable == {"entry_id", "entry_type", "payload", "previous_hash", "entry_hash"}
    assert app.execute(text("SELECT count(*) FROM ledger.entries")).scalar_one() >= 0


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize("statement", [_UPDATE, _DELETE, _TRUNCATE])
def test_runtime_role_cannot_change_or_delete_an_entry(
    app: Connection, entry_id: uuid.UUID, statement: str
) -> None:
    assert "permission denied" in _refused(app, statement, entry_id)
    assert _payload(app, entry_id) == '{"n": 1}'


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize("statement", [_UPDATE, _DELETE, _TRUNCATE])
def test_owner_cannot_change_or_delete_an_entry_without_the_mark(
    owner: Connection, entry_id: uuid.UUID, statement: str
) -> None:
    assert "append-only" in _refused(owner, statement, entry_id)
    assert _payload(owner, entry_id) == '{"n": 1}'


@pytest.mark.req("REQ-55")
def test_runtime_role_cannot_set_the_rewrite_mark(app: Connection, entry_id: uuid.UUID) -> None:
    mark = (
        "INSERT INTO ledger.rewrite_permits (transaction_id, reason) "
        "VALUES (txid_current(), 'attempt')"
    )
    assert "permission denied" in _refused(app, mark, entry_id)


@pytest.mark.req("REQ-55")
def test_a_session_setting_does_not_stand_in_for_the_mark(
    owner: Connection, entry_id: uuid.UUID
) -> None:
    owner.execute(text("SELECT set_config('mandate.ledger_rewrite', 'on', false)"))
    owner.execute(text("SELECT set_config('application_name', 'migration', false)"))
    assert "append-only" in _refused(owner, _UPDATE, entry_id)


@pytest.mark.req("REQ-55")
def test_a_marked_owner_transaction_can_rewrite_and_the_mark_ends_with_it(
    owner: Connection, entry_id: uuid.UUID
) -> None:
    owner.execute(text("BEGIN"))
    owner.execute(
        text(
            "INSERT INTO ledger.rewrite_permits (transaction_id, reason) "
            "VALUES (txid_current(), 'journey: prove the mark works')"
        )
    )
    owner.execute(text(_UPDATE), {"entry_id": entry_id})
    assert _payload(owner, entry_id) == '{"n": 2}'
    owner.execute(text("ROLLBACK"))

    assert _payload(owner, entry_id) == '{"n": 1}'
    assert "append-only" in _refused(owner, _UPDATE, entry_id)


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO ledger.entries (sequence, entry_type, payload) "
        "OVERRIDING SYSTEM VALUE VALUES (900000, 'journey_probe', CAST('{}' AS jsonb))",
        "INSERT INTO ledger.entries (sequence, entry_type, payload) "
        "VALUES (900001, 'journey_probe', CAST('{}' AS jsonb))",
        "INSERT INTO ledger.entries (entry_type, payload, recorded_at) "
        "VALUES ('journey_probe', CAST('{}' AS jsonb), '2020-01-01')",
    ],
)
def test_runtime_role_cannot_choose_an_entry_sequence_or_time(
    app: Connection, statement: str
) -> None:
    refusal = _refused(app, statement, uuid.uuid4())
    assert "permission denied" in refusal or "non-DEFAULT value" in refusal


@pytest.mark.req("REQ-55")
def test_a_permit_for_another_transaction_is_refused(owner: Connection) -> None:
    planted = (
        "INSERT INTO ledger.rewrite_permits (transaction_id, reason) "
        "VALUES (txid_current() + 2, 'planted for later')"
    )
    assert "only valid for the current transaction" in _refused(owner, planted, uuid.uuid4())
