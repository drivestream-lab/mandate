"""Journey: the deployed service connects as mandate_app and never holds the owner's credentials.

Runs against the stack `make deploy` started (never the lab: it needs the service's container
and writes nothing, but it reads the owner's password). Settings come from the environment:

    MANDATE_SERVICE_URL                         the deployed service (make exports it)
    DEPLOY_PROJECT                              the Compose project of that stack (make exports it)
    MANDATE_DB_HOST, MANDATE_DB_PORT, MANDATE_DB_NAME,
    MANDATE_DB_OWNER_PASSWORD, MANDATE_DB_APP_PASSWORD

A missing setting fails the test; it never skips. The service's database session is observed
from outside: the owner reads pg_stat_activity for the sessions the service names "mandate".
No endpoint reports it, so nothing about the session leaks through the service.
"""

import json
import os
import subprocess
import urllib.request
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection
from sqlalchemy.exc import DBAPIError, OperationalError

SERVICE_APPLICATION_NAME = "mandate"
OWNER_KEYS = ("POSTGRES_MIGRATION_USER", "POSTGRES_MIGRATION_PASSWORD_FILE")


def _setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"{name} is not set; see this file's docstring for the settings it needs")
    return value


def _connect(role: str, password_setting: str) -> Iterator[Connection]:
    url = URL.create(
        "postgresql+psycopg2",
        username=role,
        password=_setting(password_setting),
        host=_setting("MANDATE_DB_HOST"),
        port=int(_setting("MANDATE_DB_PORT")),
        database=_setting("MANDATE_DB_NAME"),
    )
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        yield connection
    engine.dispose()


@pytest.fixture(name="owner")
def owner_connection() -> Iterator[Connection]:
    yield from _connect("mandate_owner", "MANDATE_DB_OWNER_PASSWORD")


@pytest.fixture(name="app")
def app_connection() -> Iterator[Connection]:
    yield from _connect("mandate_app", "MANDATE_DB_APP_PASSWORD")


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


@pytest.fixture(name="container")
def service_container() -> str:
    project = _setting("DEPLOY_PROJECT")
    found = _docker(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        "label=com.docker.compose.service=mandate",
    )
    ids = found.stdout.split()
    assert len(ids) == 1, f"expected one service container in project {project}: {found.stderr}"
    return ids[0]


def _ask_service_to_use_the_database() -> None:
    """The detailed health check opens a database connection from the service's pool."""
    base = _setting("MANDATE_SERVICE_URL").rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"{base}/health?detailed=true", timeout=15) as response:
        assert response.status == 200


@pytest.mark.req("REQ-55")
def test_the_service_database_session_is_the_app_role(owner: Connection) -> None:
    _ask_service_to_use_the_database()

    users = {
        row[0]
        for row in owner.execute(
            text(
                "SELECT DISTINCT usename FROM pg_stat_activity "
                "WHERE application_name = :name AND datname = current_database()"
            ),
            {"name": SERVICE_APPLICATION_NAME},
        ).all()
    }

    assert users == {"mandate_app"}


@pytest.mark.req("REQ-55")
def test_the_role_the_service_runs_as_cannot_rewrite_the_ledger(
    owner: Connection, app: Connection
) -> None:
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        granted = owner.execute(
            text("SELECT has_table_privilege('mandate_app', 'ledger.entries', :privilege)"),
            {"privilege": privilege},
        ).scalar_one()
        assert granted is False, f"mandate_app holds {privilege} on ledger.entries"

    with pytest.raises(DBAPIError) as refusal:
        app.execute(text("UPDATE ledger.entries SET entry_type = entry_type"))
    assert "permission denied" in str(refusal.value)


@pytest.mark.req("REQ-55")
def test_the_running_service_does_not_hold_the_owner_credentials(container: str) -> None:
    owner_password = _setting("MANDATE_DB_OWNER_PASSWORD")
    app_password = _setting("MANDATE_DB_APP_PASSWORD")
    assert owner_password != app_password, "the owner and app passwords must differ"

    # The entrypoint execs the service as the app user, so it is process 1 and its environment is
    # the service's; only that user may read it (root in the container may not).
    environ = _docker("exec", "-u", "app", container, "cat", "/proc/1/environ")
    assert environ.returncode == 0, environ.stderr
    entries = [entry for entry in environ.stdout.split("\0") if entry]
    pairs = dict(entry.split("=", 1) for entry in entries if "=" in entry)

    assert pairs.get("POSTGRES_USER") == "mandate_app"
    assert not [key for key in OWNER_KEYS if key in pairs]
    assert owner_password not in pairs.values()
    command = _docker("exec", "-u", "app", container, "cat", "/proc/1/cmdline").stdout
    assert "src.main" in command


@pytest.mark.req("REQ-55")
def test_no_password_value_is_in_the_container_environment(container: str) -> None:
    passwords = [_setting("MANDATE_DB_OWNER_PASSWORD"), _setting("MANDATE_DB_APP_PASSWORD")]

    inspected = _docker("inspect", "-f", "{{json .Config.Env}}", container)
    assert inspected.returncode == 0, inspected.stderr
    environ = _docker("exec", "-u", "app", container, "cat", "/proc/1/environ")
    assert environ.returncode == 0, environ.stderr

    # Only counts are reported: a password must never be printed.
    assert sum(password in inspected.stdout for password in passwords) == 0
    assert sum(password in environ.stdout for password in passwords) == 0
    assert "POSTGRES_PASSWORD_FILE=" in inspected.stdout


@pytest.mark.req("REQ-55")
def test_the_service_user_reads_its_own_password_file_but_not_the_owners(container: str) -> None:
    environ = _docker("exec", "-u", "app", container, "cat", "/proc/1/environ")
    pairs = dict(e.split("=", 1) for e in environ.stdout.split("\0") if "=" in e)
    assert "POSTGRES_MIGRATION_PASSWORD_FILE" not in pairs

    inspected = _docker("inspect", "-f", "{{json .Config.Env}}", container).stdout
    owner_path = next(
        e.split("=", 1)[1]
        for e in json.loads(inspected)
        if e.startswith("POSTGRES_MIGRATION_PASSWORD_FILE=")
    )

    assert (
        _docker("exec", "-u", "app", container, "cat", pairs["POSTGRES_PASSWORD_FILE"]).returncode
        == 0
    )
    assert _docker("exec", "-u", "app", container, "cat", owner_path).returncode != 0


def _logs_in(role: str, password: str) -> bool:
    url = URL.create(
        "postgresql+psycopg2",
        username=role,
        password=password,
        host=_setting("MANDATE_DB_HOST"),
        port=int(_setting("MANDATE_DB_PORT")),
        database=_setting("MANDATE_DB_NAME"),
    )
    engine = create_engine(url, connect_args={"connect_timeout": 5})
    try:
        with engine.connect():
            return True
    except OperationalError:
        return False
    finally:
        engine.dispose()


@pytest.mark.req("REQ-55")
def test_no_value_in_the_service_environment_logs_in_as_the_owner_or_the_superuser(
    container: str,
) -> None:
    environ = _docker("exec", "-u", "app", container, "cat", "/proc/1/environ")
    assert environ.returncode == 0, environ.stderr
    values = {entry.split("=", 1)[1] for entry in environ.stdout.split("\0") if "=" in entry} - {""}
    assert len(values) > 5

    # Only counts are reported: a value that logs in must never be printed.
    owner_hits = sum(_logs_in("mandate_owner", value) for value in values)
    superuser_hits = sum(_logs_in("postgres", value) for value in values)
    assert owner_hits == 0, f"{owner_hits} environment values log in as mandate_owner"
    assert superuser_hits == 0, f"{superuser_hits} environment values log in as postgres"
    assert _logs_in("mandate_app", _setting("MANDATE_DB_APP_PASSWORD"))


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize(
    ("env", "named"),
    [
        (
            {"POSTGRES_USER": "mandate_app", "POSTGRES_PASSWORD_FILE": "/etc/hostname"},
            "POSTGRES_MIGRATION_USER",
        ),
        (
            {
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
            },
            "POSTGRES_USER",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
            },
            "POSTGRES_MIGRATION_PASSWORD_FILE",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/no/such/file",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
            },
            "POSTGRES_PASSWORD_FILE",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/no/such/file",
            },
            "POSTGRES_MIGRATION_PASSWORD_FILE",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_PASSWORD": "x",
            },
            "POSTGRES_PASSWORD",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_PASSWORD": "",
            },
            "POSTGRES_PASSWORD",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_PASSWORD": "x",
            },
            "POSTGRES_MIGRATION_PASSWORD",
        ),
        (
            {
                "POSTGRES_USER": "mandate_app",
                "POSTGRES_PASSWORD_FILE": "/etc/hostname",
                "POSTGRES_MIGRATION_USER": "mandate_owner",
                "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
                "PGPASSWORD": "x",
            },
            "PGPASSWORD",
        ),
    ],
)
def test_a_missing_credential_or_file_stops_the_start_and_names_it(
    container: str, env: dict[str, str], named: str
) -> None:
    image = _docker("inspect", "-f", "{{.Config.Image}}", container).stdout.strip()
    assert image

    env_args = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]
    started = _docker("run", "--rm", "--user", "0:0", *env_args, image)

    assert started.returncode != 0
    assert named in started.stdout
    assert "PostgreSQL is ready" not in started.stdout


@pytest.mark.req("REQ-55")
def test_the_image_refuses_to_start_as_a_non_root_user(container: str) -> None:
    image = _docker("inspect", "-f", "{{.Config.Image}}", container).stdout.strip()
    env = {
        "POSTGRES_USER": "mandate_app",
        "POSTGRES_PASSWORD_FILE": "/etc/hostname",
        "POSTGRES_MIGRATION_USER": "mandate_owner",
        "POSTGRES_MIGRATION_PASSWORD_FILE": "/etc/hostname",
    }
    env_args = [arg for key, value in env.items() for arg in ("-e", f"{key}={value}")]

    for user_args in ([], ["--user", "app"]):
        started = _docker("run", "--rm", *user_args, *env_args, image)
        assert started.returncode != 0
        assert "must start as root" in started.stdout
        assert "PostgreSQL is ready" not in started.stdout


@pytest.mark.req("REQ-55")
@pytest.mark.parametrize("directory", ["src", "scripts", "postgres_migrations"])
def test_the_service_user_cannot_write_the_code_the_entrypoint_runs_as_root(
    container: str, directory: str
) -> None:
    probe = _docker("exec", "-u", "app", container, "touch", f"/app/{directory}/probe")
    assert probe.returncode != 0
    overwrite = _docker(
        "exec", "-u", "app", container, "sh", "-c",
        f"find /app/{directory} -type f -writable | head -1",
    )  # fmt: skip
    assert overwrite.stdout.strip() == ""
