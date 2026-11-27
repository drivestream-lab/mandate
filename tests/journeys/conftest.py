"""Journey session setup: one ephemeral stack and one GitHub namespace per run.

`make journeys` starts the stack (pinned Paperclip with its own database, Postgres, Temporal)
under a Compose project named for this run, hands the tests its addresses, and removes it at
the end, also when the run fails or is interrupted. Host ports are picked by Docker, so two
runs at the same time share nothing.

GitHub work happens only in the sandbox repos and only under this run's namespace (a branch
prefix and an issue title prefix). Teardown deletes every branch and closes every issue under
that namespace. The test App's credentials are read by path from ~/.mandate/secrets/test/
(override the folder with MANDATE_TEST_SECRETS_DIR); a token or key is never printed.
"""

import os
import secrets
import signal
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import FrameType

import pytest

from tests.journeys.journey_support import (
    AppCredentials,
    RunNamespace,
    SandboxGitHub,
    StackAddresses,
)

_ROOT = Path(__file__).resolve().parents[2]


def _secrets_folder() -> Path:
    override = os.environ.get("MANDATE_TEST_SECRETS_DIR")
    return Path(override) if override else Path.home() / ".mandate" / "secrets" / "test"


def _scripts_env(password: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
    env["STACK_DB_PASSWORD"] = password
    return env


@pytest.fixture(scope="session")
def run_namespace() -> RunNamespace:
    """This run's id and the names it may use in the sandbox repos."""
    return RunNamespace(run_id=uuid.uuid4().hex[:10])


def _interrupt_on_terminate(signum: int, frame: FrameType | None) -> None:
    """Treat SIGTERM like Ctrl-C so the teardown below always runs."""
    raise KeyboardInterrupt


@pytest.fixture(scope="session", autouse=True)
def journey_stack(run_namespace: RunNamespace) -> Iterator[StackAddresses]:
    """Bring the run's stack up, and take it down afterwards whatever the outcome.

    The try opens before the up call, so a failure or an interrupt (SIGINT or SIGTERM) while
    the stack starts is torn down too; the down script is safe on a stack that is half up or
    absent. A teardown that fails is reported and fails the session.
    """
    run_id = run_namespace.run_id
    password = secrets.token_hex(16)
    env = _scripts_env(password)
    previous_handler = signal.signal(signal.SIGTERM, _interrupt_on_terminate)
    try:
        up = subprocess.run(
            [str(_ROOT / "scripts" / "test_stack_up.sh"), run_id],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if up.returncode != 0:
            pytest.exit(
                f"journey stack failed to start:\n{up.stderr[-2000:].replace(password, '<redacted>')}",
                returncode=1,
            )
        details = dict(line.split("=", 1) for line in up.stdout.splitlines() if "=" in line)
        yield StackAddresses(
            project=details["STACK_PROJECT"],
            paperclip_url=details["PAPERCLIP_URL"],
            postgres_port=int(details["POSTGRES_PORT"]),
            temporal_address=details["TEMPORAL_ADDRESS"],
            postgres_user="mandate",
            postgres_database="mandate",
            postgres_password=password,
        )
    finally:
        down = subprocess.run(
            [str(_ROOT / "scripts" / "test_stack_down.sh"), run_id],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        signal.signal(signal.SIGTERM, previous_handler)
        if down.returncode != 0:
            detail = down.stderr[-2000:].replace(password, "<redacted>")
            raise RuntimeError(f"journey stack teardown failed for {run_id}:\n{detail}")


@pytest.fixture(scope="session")
def test_app_credentials() -> AppCredentials:
    """The test App's credentials, read by path from the secrets folder."""
    return AppCredentials(_secrets_folder())


@pytest.fixture(scope="session")
def sandbox_github(
    test_app_credentials: AppCredentials, run_namespace: RunNamespace
) -> Iterator[SandboxGitHub]:
    """GitHub access to the sandbox repos within this run's namespace; cleaned up at the end."""
    sandbox = SandboxGitHub(test_app_credentials, run_namespace)
    try:
        yield sandbox
    finally:
        sandbox.cleanup()
