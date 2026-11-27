"""Support code for the journey stack: addresses, the run's GitHub namespace, the test App.

Everything here is plain code the fixtures in conftest.py assemble. A token or key is never
printed; objects that hold one redact it in their repr.
"""

import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import jwt
from pydantic import BaseModel

_GITHUB_API = "https://api.github.com"
_GITHUB_OWNER = "drivestream-lab"
SANDBOX_REPOS = ("mandate-sandbox-svc", "mandate-sandbox-meta")


@dataclass(frozen=True)
class StackAddresses:
    """Where the run's services listen on this host, and the one credential they share."""

    project: str
    paperclip_url: str
    postgres_port: int
    temporal_address: str
    postgres_user: str
    postgres_database: str
    postgres_password: str

    def __repr__(self) -> str:
        return f"StackAddresses(project={self.project!r}, paperclip_url={self.paperclip_url!r})"


@dataclass(frozen=True)
class RunNamespace:
    """The names this run may use in the sandbox repos."""

    run_id: str

    @property
    def prefix(self) -> str:
        return f"journey-{self.run_id}"

    def branch(self, name: str) -> str:
        return f"{self.prefix}/{name}"

    def issue_title(self, title: str) -> str:
        return f"[{self.prefix}] {title}"


class _Repository(BaseModel):
    name: str


class _InstallationToken(BaseModel):
    token: str
    repositories: list[_Repository] = []

    def __repr__(self) -> str:
        return "_InstallationToken(token=<redacted>)"


class _RefObject(BaseModel):
    sha: str


class _Ref(BaseModel):
    ref: str
    object: _RefObject


class _RepoInfo(BaseModel):
    default_branch: str


class _IssueSummary(BaseModel):
    number: int
    title: str
    pull_request: dict[str, str] | None = None


class AppCredentials:
    """The test App's id, installation and private key, read from files by path."""

    def __init__(self, folder: Path) -> None:
        self.app_id = (folder / "github-app-id").read_text(encoding="utf-8").strip()
        self.installation_id = (
            (folder / "github-app-installation-id").read_text(encoding="utf-8").strip()
        )
        keys = sorted(folder.glob("*.pem"))
        if len(keys) != 1:
            raise RuntimeError(f"expected exactly one private key (.pem) in {folder}")
        self.private_key_path = keys[0]

    def __repr__(self) -> str:
        return "AppCredentials(<paths only>)"

    def installation_token(self, repositories: tuple[str, ...]) -> str:
        """Mint a short-lived installation token for the given repos. Never log the result."""
        now = int(time.time())
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key_path.read_text(encoding="utf-8"),
            algorithm="RS256",
        )
        response = httpx.post(
            f"{_GITHUB_API}/app/installations/{self.installation_id}/access_tokens",
            headers=_headers(app_jwt),
            json={"repositories": list(repositories)},
            timeout=30,
        )
        response.raise_for_status()
        granted = _InstallationToken.model_validate_json(response.content)
        names = {repo.name for repo in granted.repositories}
        if names != set(repositories):
            raise RuntimeError(f"the test App token does not cover exactly {repositories}")
        return granted.token


class SandboxGitHub:
    """Branches and issues in the sandbox repos, all inside one run's namespace."""

    def __init__(self, credentials: AppCredentials, namespace: RunNamespace) -> None:
        self._credentials = credentials
        self._namespace = namespace
        self._created_issues: list[tuple[str, int]] = []

    def __repr__(self) -> str:
        return f"SandboxGitHub(namespace={self._namespace.prefix!r})"

    def _client(self) -> httpx.Client:
        token = self._credentials.installation_token(SANDBOX_REPOS)
        return httpx.Client(
            base_url=f"{_GITHUB_API}/repos/{_GITHUB_OWNER}",
            headers=_headers(token),
            timeout=30,
        )

    def create_branch(self, repo: str, name: str) -> str:
        """Create `<run prefix>/<name>` from the repo's default branch; return its full name."""
        full_name = self._namespace.branch(name)
        with self._client() as client:
            info = _RepoInfo.model_validate_json(client.get(f"/{repo}").raise_for_status().content)
            base = _Ref.model_validate_json(
                client.get(f"/{repo}/git/ref/heads/{info.default_branch}")
                .raise_for_status()
                .content
            )
            client.post(
                f"/{repo}/git/refs",
                json={"ref": f"refs/heads/{full_name}", "sha": base.object.sha},
            ).raise_for_status()
        return full_name

    def branch_exists(self, repo: str, full_name: str) -> bool:
        with self._client() as client:
            return client.get(f"/{repo}/git/ref/heads/{full_name}").status_code == 200

    def create_issue(self, repo: str, title: str, body: str = "") -> int:
        with self._client() as client:
            response = client.post(
                f"/{repo}/issues",
                json={"title": self._namespace.issue_title(title), "body": body},
            ).raise_for_status()
        number = int(response.json()["number"])
        self._created_issues.append((repo, number))
        return number

    def issue_state(self, repo: str, number: int) -> str:
        with self._client() as client:
            return str(client.get(f"/{repo}/issues/{number}").raise_for_status().json()["state"])

    def cleanup(self) -> None:
        """Delete this run's branches and close its issues. Safe to call more than once."""
        with self._client() as client:
            for repo in SANDBOX_REPOS:
                refs_url = f"/{repo}/git/matching-refs/heads/{self._namespace.prefix}/"
                for ref in _refs(client.get(refs_url).raise_for_status().content):
                    client.delete(f"/{repo}/git/{ref.ref}")
                listing = client.get(f"/{repo}/issues", params={"state": "open", "per_page": 100})
                for issue in _issues(listing.raise_for_status().content):
                    if issue.pull_request is None and issue.title.startswith(
                        f"[{self._namespace.prefix}]"
                    ):
                        client.patch(
                            f"/{repo}/issues/{issue.number}",
                            json={"state": "closed", "state_reason": "not_planned"},
                        )
        self._created_issues.clear()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _refs(payload: bytes) -> list[_Ref]:
    return [_Ref.model_validate(item) for item in httpx.Response(200, content=payload).json()]


def _issues(payload: bytes) -> list[_IssueSummary]:
    return [
        _IssueSummary.model_validate(item) for item in httpx.Response(200, content=payload).json()
    ]
