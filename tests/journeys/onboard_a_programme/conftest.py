"""Fixtures for onboarding a programme: the sandbox meta repo, real GitHub access, hired agents.

The programme configuration is committed to a branch of mandate-sandbox-meta under this run's
namespace (the session cleanup deletes it), and the services read it back at that commit.
"""

import base64
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from src.business_services.programmes.programme_from_meta_service import (
    ProgrammeFromMetaService,
    RepositoryAccessError,
)
from src.business_services.programmes.programme_readiness_service import ProgrammeReadinessService
from src.infra_services.paperclip_service import PaperclipService
from tests.contract.paperclip.conftest import mandate_identity, paperclip
from tests.contract.paperclip.paperclip_stack import MandateIdentity
from tests.journeys.journey_support import SANDBOX_REPOS, AppCredentials, RunNamespace

__all__ = ["mandate_identity", "paperclip"]

META_REPO = "mandate-sandbox-meta"
_OWNER = "drivestream-lab"
_FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "onboard_a_programme"
_ROLE_AGENTS = ("sandbox-coder", "sandbox-design-decider")


class GitHubRepositoryAccess:
    """Reads the sandbox repos through the test App, as Mandate's GitHub access will."""

    def __init__(self, credentials: AppCredentials) -> None:
        self._credentials = credentials

    def _client(self) -> httpx.AsyncClient:
        token = self._credentials.installation_token(SANDBOX_REPOS)
        return httpx.AsyncClient(
            base_url=f"https://api.github.com/repos/{_OWNER}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.raw+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30,
        )

    async def read_file(self, repo: str, path: str, ref: str) -> str:
        async with self._client() as client:
            response = await client.get(f"/{repo}/contents/{path}", params={"ref": ref})
        if not response.is_success:
            raise RepositoryAccessError(
                f"{repo}/{path} at {ref}: GitHub answered {response.status_code}"
            )
        return response.text

    async def check_access(self, repo: str) -> None:
        async with self._client() as client:
            response = await client.get(f"/{repo}")
        if not response.is_success:
            raise RepositoryAccessError(f"{repo}: GitHub answered {response.status_code}")


@pytest.fixture(scope="session")
def meta_commit(test_app_credentials: AppCredentials, run_namespace: RunNamespace) -> str:
    """A commit on a run branch of the meta repo that holds the fixture programme.yaml."""
    token = test_app_credentials.installation_token(SANDBOX_REPOS)
    with httpx.Client(
        base_url=f"https://api.github.com/repos/{_OWNER}/{META_REPO}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    ) as client:
        base = client.get("/git/ref/heads/develop").raise_for_status().json()["object"]["sha"]
        branch = run_namespace.branch("programme-config")
        client.post(
            "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": base}
        ).raise_for_status()
        content = (_FIXTURE / "sandbox_meta_config" / "programme.yaml").read_bytes()
        put = client.put(
            "/contents/config/programme.yaml",
            json={
                "message": f"{run_namespace.prefix} programme configuration",
                "content": base64.b64encode(content).decode(),
                "branch": branch,
                "sha": client.get("/contents/config/programme.yaml", params={"ref": base})
                .raise_for_status()
                .json()["sha"],
            },
        ).raise_for_status()
        return str(put.json()["commit"]["sha"])


@pytest.fixture(scope="session")
def role_agents(mandate_identity: MandateIdentity) -> Iterator[tuple[str, ...]]:
    """The agents filling the fixture's roles, hired in this run's Paperclip by the board."""
    with httpx.Client(
        base_url=mandate_identity.base_url,
        headers={"Origin": mandate_identity.base_url},
        timeout=60,
    ) as board:
        board.post(
            "/api/auth/sign-in/email",
            json={
                "email": mandate_identity.board_email,
                "password": mandate_identity.board_password,
            },
        ).raise_for_status()
        for name in _ROLE_AGENTS:
            board.post(
                f"/api/companies/{mandate_identity.company_id}/agents",
                json={
                    "name": name,
                    "role": "engineer",
                    "title": name,
                    "adapterType": "process",
                    "adapterConfig": {"command": "true"},
                },
            ).raise_for_status()
    yield _ROLE_AGENTS


@pytest.fixture(scope="session")
def repository_access(test_app_credentials: AppCredentials) -> GitHubRepositoryAccess:
    return GitHubRepositoryAccess(test_app_credentials)


@pytest.fixture
def programme_from_meta(
    paperclip: PaperclipService, repository_access: GitHubRepositoryAccess
) -> ProgrammeFromMetaService:
    return ProgrammeFromMetaService(paperclip, repository_access)


@pytest.fixture
def readiness(
    paperclip: PaperclipService, repository_access: GitHubRepositoryAccess
) -> ProgrammeReadinessService:
    return ProgrammeReadinessService(paperclip, repository_access)
