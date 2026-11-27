"""Fixtures for the scripted agents: a Paperclip with Python and the agent scripts installed.

The Paperclip image has Python and no packages, and its process adapter starts commands inside
the container. So the harness copies the scripts and Mandate's role models into the container
and installs the same pydantic Mandate runs on, built for the container's platform.
"""

import json
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from pathlib import Path

import httpx
import pydantic
import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from pytest import TempPathFactory

from src.models.paperclip_models import RunStatusType
from tests.contract.paperclip.conftest import mandate_identity, paperclip
from tests.contract.paperclip.paperclip_stack import MandateIdentity
from tests.journeys.journey_support import StackAddresses

__all__ = ["mandate_identity", "paperclip"]

_ROOT = Path(__file__).resolve().parents[3]
_AGENT_HOME = "/opt/mandate"
_TERMINAL = {
    RunStatusType.SUCCEEDED,
    RunStatusType.FAILED,
    RunStatusType.CANCELLED,
    RunStatusType.TIMED_OUT,
}


def _run(*command: str) -> str:
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{command[0]} {command[1]} failed: {done.stderr[-1500:]}")
    return done.stdout.strip()


@pytest.fixture(scope="session")
def agent_host(journey_stack: StackAddresses, tmp_path_factory: TempPathFactory) -> str:
    """The Paperclip container, with the agent scripts, role models and pydantic installed."""
    container = _run("docker", "compose", "-p", journey_stack.project, "ps", "-q", "paperclip")
    stage = tmp_path_factory.mktemp("agent-stage")
    for name in ("src/__init__.py", "src/models/__init__.py", "src/models/role_output_models.py"):
        (stage / name).parent.mkdir(parents=True, exist_ok=True)
        (stage / name).write_bytes((_ROOT / name).read_bytes())
    (stage / "tests").mkdir()
    (stage / "tests" / "__init__.py").write_text("")
    agents = stage / "tests" / "agents"
    agents.mkdir()
    for script in (_ROOT / "tests" / "agents").glob("*.py"):
        (agents / script.name).write_bytes(script.read_bytes())
    arch = _run("docker", "exec", container, "uname", "-m")
    python = _run(
        "docker",
        "exec",
        container,
        "python3",
        "-c",
        "import sys;print(*sys.version_info[:2], sep='.')",
    )
    _run(
        sys.executable, "-m", "pip", "install", "--quiet", "--target", str(stage / "deps"),
        "--platform", f"manylinux2014_{arch}", "--platform", f"manylinux_2_28_{arch}",
        "--python-version", python, "--only-binary=:all:", f"pydantic=={pydantic.VERSION}",
    )  # fmt: skip
    _run("docker", "exec", container, "mkdir", "-p", _AGENT_HOME)
    _run("docker", "cp", f"{stage}/.", f"{container}:{_AGENT_HOME}")
    return container


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class RunListing(_Record):
    """One row of Paperclip's run list."""

    id: str
    issue_id: str | None = Field(default=None, alias="issueId")
    status: RunStatusType
    retry_of_run_id: str | None = Field(default=None, alias="retryOfRunId")


class RunResult(_Record):
    """What the process adapter kept of the script's output."""

    stdout: str = ""
    stderr: str = ""


class RunDetail(_Record):
    """A finished run, as Paperclip reports it."""

    id: str
    status: RunStatusType
    exit_code: int | None = Field(default=None, alias="exitCode")
    result_json: RunResult | None = Field(default=None, alias="resultJson")

    @property
    def stdout(self) -> str:
        return self.result_json.stdout if self.result_json else ""

    @property
    def stderr(self) -> str:
        return self.result_json.stderr if self.result_json else ""


_RUNS = TypeAdapter(list[RunListing])


class AgentDesk:
    """The board's view of Paperclip: hire a scripted agent, give it a brief, wait for its run."""

    def __init__(self, identity: MandateIdentity) -> None:
        self.identity = identity
        self._http = httpx.Client(
            base_url=identity.base_url, headers={"Origin": identity.base_url}, timeout=60
        )
        self._http.post(
            "/api/auth/sign-in/email",
            json={"email": identity.board_email, "password": identity.board_password},
        ).raise_for_status()

    def close(self) -> None:
        self._http.close()

    def hire(self, name: str, script: str) -> str:
        """A process-adapter agent that runs `tests/agents/<script>` and nothing else."""
        config = {
            "command": "python3",
            "args": [f"tests/agents/{script}"],
            "cwd": _AGENT_HOME,
            "env": {"PYTHONPATH": f"{_AGENT_HOME}:{_AGENT_HOME}/deps"},
        }
        body = {
            "name": name,
            "role": "engineer",
            "title": name,
            "adapterType": "process",
            "adapterConfig": config,
        }
        response = self._http.post(f"/api/companies/{self.identity.company_id}/agents", json=body)
        return str(response.raise_for_status().json()["id"])

    def assign(self, agent_id: str, title: str, brief: Mapping[str, object]) -> str:
        """File an issue holding the brief and assign it to the agent, which starts its run."""
        body = {"title": title, "description": json.dumps(brief), "assigneeAgentId": agent_id}
        response = self._http.post(f"/api/companies/{self.identity.company_id}/issues", json=body)
        return str(response.raise_for_status().json()["id"])

    def first_finished_run(self, agent_id: str, issue_id: str) -> RunDetail:
        """The earliest run on the issue that has reached an end state."""
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            listing = self._http.get(
                f"/api/companies/{self.identity.company_id}/heartbeat-runs",
                params={"agentId": agent_id},
            ).raise_for_status()
            done = [
                run
                for run in _RUNS.validate_json(listing.content)
                if run.issue_id == issue_id
                and run.status in _TERMINAL
                and run.retry_of_run_id is None
            ]
            if done:
                detail = self._http.get(f"/api/heartbeat-runs/{done[0].id}").raise_for_status()
                return RunDetail.model_validate_json(detail.content)
            time.sleep(1)
        raise TimeoutError("the agent's run did not finish")


@pytest.fixture
def desk(mandate_identity: MandateIdentity, agent_host: str) -> Iterator[AgentDesk]:
    """The board's desk on the provisioned Paperclip, once the agent scripts are installed."""
    opened = AgentDesk(mandate_identity)
    try:
        yield opened
    finally:
        opened.close()
