"""Fixtures for signing a gate on real sandbox pull requests.

Three real identities take part. Mandate's own App (the test App) reads pull requests and
posts mandate/gate-decision. The author, mandate-builder, opens the pull requests. The signer,
mandate-challenger, holds the sandbox gates at L0 and signs. The author and signer tokens come
from the environment (MANDATE_JOURNEY_AUTHOR_TOKEN, MANDATE_JOURNEY_SIGNER_TOKEN); a missing
token fails the run at once. Pull requests and branches are removed at the end.
"""

import base64
import os
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict

from src.configs.github_app_settings import GitHubAppSettings
from src.infra_services.github_app_service import GitHubAppService
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import GateRule
from tests.journeys.decide_blind_first.test_call_sealed_before_the_holder_sees_the_decision import (
    app_postgres,
    throwaway_database,
)
from tests.journeys.journey_support import SANDBOX_REPOS, AppCredentials, SandboxGitHub
from tests.journeys.test_agents.conftest import agent_host, desk
from tests.contract.paperclip.conftest import mandate_identity, paperclip
from tests.contract.paperclip.paperclip_stack import MandateIdentity

__all__ = [
    "agent_host",
    "app_postgres",
    "desk",
    "mandate_identity",
    "paperclip",
    "throwaway_database",
]

OWNER = "drivestream-lab"
REPO = SANDBOX_REPOS[1]
GATE_LABEL = "spec-lgtm"
SIGNER_LOGIN = "mandate-challenger[bot]"
GATE_RULE = GateRule(
    label=GATE_LABEL, branch="develop", rung=RungType.L2, holders=frozenset({SIGNER_LOGIN})
)
"""The test gate configuration: the sandbox gates are at L2, so the deciding role, here the
challenger App, signs and may be an App."""
DESIGN_GATE_RULE = GateRule(
    label="design-lgtm", branch="develop", rung=RungType.L2, holders=frozenset({SIGNER_LOGIN})
)
"""A second gate of the same branch, to show a pull request naming two gates fails."""
L0_GATE_RULE = GateRule(
    label=GATE_LABEL, branch="develop", rung=RungType.L0, holders=frozenset({SIGNER_LOGIN})
)
"""The same gate at L0, where only a person may sign: an App's Approve is refused."""

_SECRETS = Path.home() / ".mandate" / "secrets" / "test"


class _Created(BaseModel):
    model_config = ConfigDict(extra="ignore")
    number: int
    node_id: str


class _Head(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class _Written(BaseModel):
    model_config = ConfigDict(extra="ignore")
    commit: _Head


class _PullHead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    head: _Head
    node_id: str


class _Status(BaseModel):
    model_config = ConfigDict(extra="ignore")
    context: str
    state: str
    description: str | None = None


class _Combined(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statuses: list[_Status]


def _token_from_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(
            f"{name} is not set: run the journey under the swarm role that supplies it "
            "(see tests/journeys/README.md)",
            pytrace=False,
        )
    return value


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"https://api.github.com/repos/{OWNER}/{REPO}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )


class SandboxPullRequest:
    """One draft pull request authored by mandate-builder, signed or not by mandate-challenger."""

    def __init__(
        self, ref: PullRequestRef, branch: str, author: str, signer: str, mandate: str
    ) -> None:
        self.ref = ref
        self._branch = branch
        self._author = author
        self._signer = signer
        self._mandate = mandate
        self._extra: list[int] = []

    def head_sha(self) -> str:
        with _client(self._mandate) as client:
            reply = client.get(f"/pulls/{self.ref.number}").raise_for_status()
        return _PullHead.model_validate_json(reply.content).head.sha

    def author_pushes(self, name: str) -> str:
        """A new commit on the branch by the author; returns the head once the pull shows it."""
        with _client(self._author) as client:
            reply = client.put(
                f"/contents/{name}.txt",
                json={
                    "message": f"journey commit {name}",
                    "content": base64.b64encode(name.encode()).decode(),
                    "branch": self._branch,
                },
            ).raise_for_status()
        pushed = _Written.model_validate_json(reply.content).commit.sha
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if self.head_sha() == pushed:
                    return pushed
            except httpx.TransportError:
                pass  # a network blip while waiting: ask again until the deadline
            time.sleep(1)
        raise TimeoutError("the pull request did not move to the pushed commit")

    def signer_labels(self) -> None:
        self.add_label(self._signer, GATE_LABEL)

    def author_adds_label(self, label: str) -> None:
        """The author picks another gate label for the same pull request."""
        self.add_label(self._author, label)

    def add_label(self, token: str, label: str) -> None:
        with _client(token) as client:
            client.post(
                f"/issues/{self.ref.number}/labels", json={"labels": [label]}
            ).raise_for_status()

    def review(self, token: str, event: str, body: str) -> None:
        with _client(token) as client:
            client.post(
                f"/pulls/{self.ref.number}/reviews",
                json={"commit_id": self.head_sha(), "event": event, "body": body},
            ).raise_for_status()

    def attestation(self) -> str:
        return (
            "attestation:\n  initiative: INIT-JOURNEY\n"
            f"  head: {self.head_sha()}\n  gate: {GATE_LABEL}\n  repo: {REPO}\n"
            f"  pull_request: {self.ref.number}\n  digests: ['{'c' * 64}']\n"
            "  artifact_paths: [journey.txt]\n"
        )

    def retarget(self, base: str) -> None:
        """The author changes the pull request's base branch."""
        with _client(self._author) as client:
            client.patch(f"/pulls/{self.ref.number}", json={"base": base}).raise_for_status()

    def open_stacked_pull_request(self, name: str) -> int:
        """A pull request into develop on top of this branch: its history holds this commit but
        its head is a later one."""
        branch = f"{self._branch}-{name}"
        with _client(self._author) as client:
            client.post(
                "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": self.head_sha()}
            ).raise_for_status()
            client.put(
                f"/contents/{name}.txt",
                json={
                    "message": f"stacked {name}",
                    "content": base64.b64encode(name.encode()).decode(),
                    "branch": branch,
                },
            ).raise_for_status()
            created = _Created.model_validate_json(
                client.post(
                    "/pulls",
                    json={"title": f"[journey] {name}", "head": branch, "base": "develop"},
                )
                .raise_for_status()
                .content
            )
        self._extra.append(created.number)
        return created.number

    def open_second_pull_on_same_head(self, name: str) -> int:
        """Another open pull request into develop whose head is this very commit."""
        head = self.head_sha()
        branch = f"{self._branch}-{name}"
        with _client(self._author) as client:
            client.post(
                "/git/refs", json={"ref": f"refs/heads/{branch}", "sha": head}
            ).raise_for_status()
            created = _Created.model_validate_json(
                client.post(
                    "/pulls",
                    json={"title": f"[journey] {name}", "head": branch, "base": "develop"},
                )
                .raise_for_status()
                .content
            )
        self._extra.append(created.number)
        return created.number

    def signer_marks_ready(self) -> None:
        with _client(self._signer) as client:
            node = _PullHead.model_validate_json(
                client.get(f"/pulls/{self.ref.number}").raise_for_status().content
            ).node_id
        mutation = (
            "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
            "{pullRequest{isDraft}}}"
        )
        reply = httpx.post(
            "https://api.github.com/graphql",
            headers={"Authorization": f"Bearer {self._signer}"},
            json={"query": mutation, "variables": {"id": node}},
            timeout=30,
        )
        reply.raise_for_status()
        if reply.json().get("errors"):
            raise RuntimeError("the signer could not mark the pull request ready")

    def signer_signs(self) -> None:
        """The signoff as the holder gives it: label, Approve with attestation, ready."""
        self.signer_labels()
        self.review(self._signer, "APPROVE", self.attestation())
        self.signer_marks_ready()

    def signer_reviews(self, event: str) -> None:
        self.review(self._signer, event, "technical review")

    def mandate_approves(self) -> None:
        """Mandate's own App approving: it holds no gate, so this must not count."""
        self.review(self._mandate, "APPROVE", self.attestation())

    def gate_decision(self) -> _Status | None:
        """The mandate/gate-decision status on the current head, read back from GitHub."""
        with _client(self._mandate) as client:
            reply = client.get(f"/commits/{self.head_sha()}/status").raise_for_status()
        found = [s for s in _Combined.model_validate_json(reply.content).statuses
                 if s.context == "mandate/gate-decision"]  # fmt: skip
        return found[0] if found else None

    def close(self) -> None:
        with _client(self._author) as client:
            for number in (self.ref.number, *self._extra):
                client.patch(f"/pulls/{number}", json={"state": "closed"})


class SandboxDesk:
    """Opens draft pull requests as the author and closes them at the end."""

    def __init__(self, sandbox: SandboxGitHub, author: str, signer: str, mandate: str) -> None:
        self._sandbox = sandbox
        self._author = author
        self._signer = signer
        self._mandate = mandate
        self._opened: list[SandboxPullRequest] = []

    def open_pull_request(self, name: str) -> SandboxPullRequest:
        branch = self._sandbox.create_branch(REPO, name)
        with _client(self._author) as client:
            client.put(
                f"/contents/{name}.txt",
                json={
                    "message": f"journey file {name}",
                    "content": base64.b64encode(name.encode()).decode(),
                    "branch": branch,
                },
            ).raise_for_status()
            created = _Created.model_validate_json(
                client.post(
                    "/pulls",
                    json={
                        "title": f"[journey] {name}",
                        "head": branch,
                        "base": "develop",
                        "draft": True,
                    },
                )
                .raise_for_status()
                .content
            )
        pull = SandboxPullRequest(
            PullRequestRef(repo=REPO, number=created.number),
            branch,
            self._author,
            self._signer,
            self._mandate,
        )
        self._opened.append(pull)
        return pull

    def close_all(self) -> None:
        for pull in self._opened:
            pull.close()


@pytest.fixture
def signer_token() -> str:
    return _token_from_environment("MANDATE_JOURNEY_SIGNER_TOKEN")


@pytest.fixture
def author_token() -> str:
    return _token_from_environment("MANDATE_JOURNEY_AUTHOR_TOKEN")


@pytest.fixture
def mandate_token(test_app_credentials: AppCredentials) -> str:
    return test_app_credentials.installation_token(SANDBOX_REPOS)


@pytest.fixture
def sandbox_desk(
    sandbox_github: SandboxGitHub, author_token: str, signer_token: str, mandate_token: str
) -> Iterator[SandboxDesk]:
    opened = SandboxDesk(sandbox_github, author_token, signer_token, mandate_token)
    try:
        yield opened
    finally:
        opened.close_all()


@pytest_asyncio.fixture
async def github_app() -> AsyncIterator[GitHubAppService]:
    """Mandate's GitHub client, built from the test App's credential files."""
    key = next(_SECRETS.glob("*.pem"))
    service = GitHubAppService(
        GitHubAppSettings(
            app_id_file=_SECRETS / "github-app-id",
            installation_id_file=_SECRETS / "github-app-installation-id",
            private_key_file=key,
        )
    )
    await service.initialize()
    try:
        yield service
    finally:
        await service.close()


class BoardUser:
    """The test stack's Paperclip board user, who answers questions as a person."""

    def __init__(self, identity: MandateIdentity) -> None:
        self.user_id = identity.board_user_id
        self._http = httpx.Client(
            base_url=identity.base_url, headers={"Origin": identity.base_url}, timeout=60
        )
        self._http.post(
            "/api/auth/sign-in/email",
            json={"email": identity.board_email, "password": identity.board_password},
        ).raise_for_status()

    def answer(self, issue_id: str, question_id: str, answer_id: str, option_id: str) -> None:
        self._http.post(
            f"/api/issues/{issue_id}/interactions/{question_id}/respond",
            json={"answers": [{"questionId": answer_id, "optionIds": [option_id]}]},
        ).raise_for_status()

    def close(self) -> None:
        self._http.close()


@pytest.fixture
def board_user(mandate_identity: MandateIdentity) -> Iterator[BoardUser]:
    user = BoardUser(mandate_identity)
    try:
        yield user
    finally:
        user.close()
