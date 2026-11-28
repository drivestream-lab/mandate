"""Fixtures for evidence journeys: real workflow runs on mandate-sandbox-svc.

Three callers are pushed to branches under this run's namespace (the session cleanup deletes
the branches): one pinned to the signer tag, one whose own workflow attests a forged bundle
inside the sandbox repo, and one pinned to the signer tag over a failing test. Each run is
waited for. The signer tag is a setting (EVIDENCE_SIGNER_REF); the journeys exercise whatever
tag it names. The callers are pushed by the author, mandate-builder
(MANDATE_JOURNEY_AUTHOR_TOKEN; a missing token fails the run at once). Mandate's own test App
never pushes a workflow file: it reads runs, artifacts, trees and attestations. Nothing is mocked.
"""

import base64
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict

from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import AttestationService
from src.models.evidence_models import EvidenceTarget
from tests.journeys.journey_support import SANDBOX_REPOS, AppCredentials, RunNamespace

OWNER = "drivestream-lab"
REPO = "mandate-sandbox-svc"
FULL_REPO = f"{OWNER}/{REPO}"
TEST_SET = ("tests/unit",)
_RUN_TIMEOUT_SECONDS = 600


class _Sha(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class _Ref(BaseModel):
    model_config = ConfigDict(extra="ignore")
    object: _Sha


class _Written(BaseModel):
    model_config = ConfigDict(extra="ignore")
    commit: _Sha


class _RunStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str
    conclusion: str | None


class _RunsStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    workflow_runs: list[_RunStatus]


@dataclass(frozen=True)
class EvidenceRun:
    """A pushed caller, the commit it ran on and how the run ended."""

    commit: str
    conclusion: str

    @property
    def target(self) -> EvidenceTarget:
        return EvidenceTarget(repository=FULL_REPO, commit=self.commit, test_set=TEST_SET)


def _caller(name: str, branch: str, signer_tag: str) -> str:
    return f"""name: {name}
on:
  push:
    branches: ["{branch}"]
permissions:
  contents: read
  id-token: write
  attestations: write
jobs:
  verify:
    uses: drivestream-lab/mandate-verify/.github/workflows/verify.yml@{signer_tag}
    with:
      commit: ${{{{ github.sha }}}}
"""


def _edited_caller(name: str, branch: str) -> str:
    """A caller that edited its own CI: it signs a bundle itself instead of calling the signer."""
    return f"""name: {name}
on:
  push:
    branches: ["{branch}"]
permissions:
  contents: read
  id-token: write
  attestations: write
jobs:
  forge:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          persist-credentials: false
      - name: Build a bundle outside mandate-verify
        run: |
          mkdir -p evidence
          for f in binding.json report.json environment.json; do echo '{{}}' > evidence/$f; done
          for f in junit.xml collected.txt digest-inputs.txt; do echo forged > evidence/$f; done
          tar -czf evidence.tgz -C evidence binding.json report.json environment.json junit.xml collected.txt digest-inputs.txt
      - uses: actions/attest-build-provenance@e8998f949152b193b063cb0ec769d69d929409be
        with:
          subject-path: evidence.tgz
      - uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02
        with:
          name: evidence-${{{{ github.sha }}}}-1
          path: evidence.tgz
"""


class _Pusher:
    """Commits files to a namespaced branch of the sandbox repo, as the author."""

    def __init__(self, author_token: str, namespace: RunNamespace) -> None:
        self._token = author_token
        self._namespace = namespace

    def _client(self) -> httpx.Client:
        token = self._token
        return httpx.Client(
            base_url=f"https://api.github.com/repos/{OWNER}/{REPO}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=60,
        )

    def branch_from_develop(self, name: str) -> str:
        full = self._namespace.branch(name)
        with self._client() as client:
            base = _Ref.model_validate_json(
                client.get("/git/ref/heads/develop").raise_for_status().content
            )
            client.post(
                "/git/refs", json={"ref": f"refs/heads/{full}", "sha": base.object.sha}
            ).raise_for_status()
        return full

    def commit_file(self, branch: str, path: str, text: str) -> str:
        with self._client() as client:
            response = client.put(
                f"/contents/{path}",
                json={
                    "message": f"{self._namespace.prefix} evidence journey file",
                    "content": base64.b64encode(text.encode()).decode(),
                    "branch": branch,
                },
            )
            response.raise_for_status()
        return _Written.model_validate_json(response.content).commit.sha

    def wait_for_run(self, commit: str) -> str:
        """Wait until the commit's run has finished; return its conclusion."""
        deadline = time.monotonic() + _RUN_TIMEOUT_SECONDS
        with self._client() as client:
            while time.monotonic() < deadline:
                runs = _RunsStatus.model_validate_json(
                    client.get("/actions/runs", params={"head_sha": commit}).content
                ).workflow_runs
                if runs and all(run.status == "completed" for run in runs):
                    return ",".join(sorted(run.conclusion or "none" for run in runs))
                time.sleep(10)
        raise TimeoutError(f"the run for {commit} did not finish in {_RUN_TIMEOUT_SECONDS}s")


@pytest.fixture(scope="session")
def evidence_settings() -> EvidenceSettings:
    return EvidenceSettings()


@pytest.fixture(scope="session")
def author_token() -> str:
    token = os.environ.get("MANDATE_JOURNEY_AUTHOR_TOKEN", "")
    if not token:
        pytest.exit("MANDATE_JOURNEY_AUTHOR_TOKEN is not set; the author pushes the callers", 1)
    return token


@pytest.fixture(scope="session")
def evidence_runs(
    author_token: str,
    run_namespace: RunNamespace,
    sandbox_github: object,
    evidence_settings: EvidenceSettings,
) -> dict[str, EvidenceRun]:
    """The three real runs: pinned (passes), edited caller (signs for itself), failing test."""
    pusher = _Pusher(author_token, run_namespace)
    tag = evidence_settings.signer_tag
    pinned = pusher.branch_from_develop("evidence-pinned")
    edited = pusher.branch_from_develop("evidence-edited")
    failing = pusher.branch_from_develop("evidence-failing")
    pusher.commit_file(
        failing, "tests/unit/test_the_run_fails.py", "def test_fails() -> None:\n    assert False\n"
    )
    commits = {
        "pinned": pusher.commit_file(
            pinned, ".github/workflows/evidence-pinned.yml", _caller("evidence-pinned", pinned, tag)
        ),
        "edited": pusher.commit_file(
            edited,
            ".github/workflows/evidence-edited.yml",
            _edited_caller("evidence-edited", edited),
        ),
        "failing": pusher.commit_file(
            failing,
            ".github/workflows/evidence-failing.yml",
            _caller("evidence-failing", failing, tag),
        ),
    }
    return {
        name: EvidenceRun(commit, pusher.wait_for_run(commit)) for name, commit in commits.items()
    }


@pytest_asyncio.fixture
async def attestations(
    test_app_credentials: AppCredentials, evidence_settings: EvidenceSettings
) -> AsyncIterator[AttestationService]:
    async def token() -> str:
        return test_app_credentials.installation_token(SANDBOX_REPOS)

    service = AttestationService(token, evidence_settings)
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()


@pytest.fixture
def evidence_service(attestations: AttestationService) -> EvidenceVerificationService:
    return EvidenceVerificationService(attestations)
