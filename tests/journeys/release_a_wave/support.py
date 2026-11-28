"""Helpers for the wave-merge and sweep journeys: pull requests on any sandbox repo, and the
baseline of a repository's rulesets as it stands.

Three real identities take part, as in the sign-a-gate journeys: the author (mandate-builder)
opens and moves pull requests and merges where a person would, the signer (mandate-challenger)
signs, and Mandate's own test App reads, posts the check and, at L2, signs and merges.
"""

import base64
import time

import httpx
from pydantic import BaseModel, ConfigDict

from src.engine.gates.unguarded_merge_rules import protection_digest, ruleset_digest
from src.infra_services.github_app_service import GitHubAppService
from src.models.gate_models import PullRequestRef
from src.models.sweep_models import ProtectionBaseline, RepoBaseline, RulesetBaseline

OWNER = "drivestream-lab"
GOVERNED = ("develop", "main")
AUTHOR_LOGIN = "mandate-builder[bot]"
VISIBLE_SECONDS = 240


class _Head(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


class _Pull(BaseModel):
    model_config = ConfigDict(extra="ignore")
    number: int
    node_id: str
    state: str
    draft: bool = False
    merged: bool = False
    head: _Head


class _Written(BaseModel):
    model_config = ConfigDict(extra="ignore")
    commit: _Head


class _Status(BaseModel):
    model_config = ConfigDict(extra="ignore")
    context: str
    state: str
    description: str | None = None


class _Combined(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statuses: list[_Status]


class _Merged(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sha: str


def client(repo: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"https://api.github.com/repos/{OWNER}/{repo}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )


def attestation_text(repo: str, number: int, head: str, gate: str) -> str:
    """The attestation a holder's Approve carries for this head."""
    return (
        "attestation:\n  initiative: INIT-JOURNEY\n"
        f"  head: {head}\n  gate: {gate}\n  repo: {repo}\n  pull_request: {number}\n"
        f"  digests: ['{'c' * 64}']\n  artifact_paths: [journey.txt]\n"
    )


class SandboxPull:
    """One pull request into develop on a sandbox repo, with the three identities around it."""

    def __init__(self, repo: str, number: int, branch: str, author: str, signer: str, mandate: str):
        self.repo = repo
        self.ref = PullRequestRef(repo=repo, number=number)
        self.branch = branch
        self._author = author
        self._signer = signer
        self._mandate = mandate

    def _pull(self) -> _Pull:
        with client(self.repo, self._mandate) as http:
            reply = http.get(f"/pulls/{self.ref.number}").raise_for_status()
        return _Pull.model_validate_json(reply.content)

    def head_sha(self) -> str:
        return self._pull().head.sha

    def state(self) -> str:
        """open, closed or merged."""
        pull = self._pull()
        return "merged" if pull.merged else pull.state

    def author_pushes(self, name: str) -> str:
        """The author adds a file; returns the head once the pull request shows it."""
        with client(self.repo, self._author) as http:
            reply = http.put(
                f"/contents/{name}.txt",
                json={
                    "message": f"journey commit {name}",
                    "content": base64.b64encode(name.encode()).decode(),
                    "branch": self.branch,
                },
            ).raise_for_status()
        pushed = _Written.model_validate_json(reply.content).commit.sha
        deadline = time.monotonic() + VISIBLE_SECONDS
        while time.monotonic() < deadline:
            if self.head_sha() == pushed:
                return pushed
            time.sleep(1)
        raise TimeoutError("the pull request did not move to the pushed commit")

    def author_force_pushes_to(self, sha: str) -> None:
        """The author moves the branch back to a commit it had before."""
        with client(self.repo, self._author) as http:
            http.patch(
                f"/git/refs/heads/{self.branch}", json={"sha": sha, "force": True}
            ).raise_for_status()
        deadline = time.monotonic() + VISIBLE_SECONDS
        while time.monotonic() < deadline:
            if self.head_sha() == sha:
                return
            time.sleep(1)
        raise TimeoutError("the pull request did not move back to the commit")

    def signer_signs(self, gate: str) -> str:
        """Label, Approve with the attestation, ready; returns the head signed."""
        head = self.head_sha()
        with client(self.repo, self._signer) as http:
            http.post(
                f"/issues/{self.ref.number}/labels", json={"labels": [gate]}
            ).raise_for_status()
            http.post(
                f"/pulls/{self.ref.number}/reviews",
                json={
                    "commit_id": head,
                    "event": "APPROVE",
                    "body": attestation_text(self.repo, self.ref.number, head, gate),
                },
            ).raise_for_status()
            pull = self._pull()
        if pull.draft:
            mutation = (
                "mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
                "{pullRequest{isDraft}}}"
            )
            reply = httpx.post(
                "https://api.github.com/graphql",
                headers={"Authorization": f"Bearer {self._signer}"},
                json={"query": mutation, "variables": {"id": pull.node_id}},
                timeout=30,
            )
            reply.raise_for_status()
            if reply.json().get("errors"):
                raise RuntimeError("the signer could not mark the pull request ready")
        return head

    def author_merges(self, sha: str) -> str:
        """The author merges with the sha pinned, as a person's merger would; returns the commit."""
        with client(self.repo, self._author) as http:
            reply = http.put(
                f"/pulls/{self.ref.number}/merge", json={"sha": sha, "merge_method": "merge"}
            ).raise_for_status()
        return _Merged.model_validate_json(reply.content).sha

    def gate_decision(self) -> _Status | None:
        """mandate/gate-decision on the current head, read back from GitHub."""
        deadline = time.monotonic() + 20
        while True:
            with client(self.repo, self._mandate) as http:
                reply = http.get(f"/commits/{self.head_sha()}/status").raise_for_status()
            found = [
                s
                for s in _Combined.model_validate_json(reply.content).statuses
                if s.context == "mandate/gate-decision"
            ]
            if found or time.monotonic() >= deadline:
                return found[0] if found else None
            time.sleep(1)

    def close(self) -> None:
        with client(self.repo, self._author) as http:
            http.patch(f"/pulls/{self.ref.number}", json={"state": "closed"})


def open_pull(
    repo: str,
    branch: str,
    author: str,
    signer: str,
    mandate: str,
    title: str,
    draft: bool,
    file_name: str | None = None,
) -> SandboxPull:
    """Open a pull request into develop from an existing branch; with a file name, commit it first."""
    with client(repo, author) as http:
        if file_name is not None:
            http.put(
                f"/contents/{file_name}.txt",
                json={
                    "message": f"journey file {file_name}",
                    "content": base64.b64encode(file_name.encode()).decode(),
                    "branch": branch,
                },
            ).raise_for_status()
        created = _Pull.model_validate_json(
            http.post(
                "/pulls",
                json={"title": title, "head": branch, "base": "develop", "draft": draft},
            )
            .raise_for_status()
            .content
        )
    return SandboxPull(repo, created.number, branch, author, signer, mandate)


def file_exists(repo: str, token: str, path: str, ref: str) -> bool:
    with client(repo, token) as http:
        return http.get(f"/contents/{path}", params={"ref": ref}).status_code == 200


def pull_state(repo: str, token: str, number: int) -> str:
    with client(repo, token) as http:
        pull = _Pull.model_validate_json(http.get(f"/pulls/{number}").raise_for_status().content)
    return "merged" if pull.merged else pull.state


def commit_parents(repo: str, token: str, sha: str) -> list[str]:
    with client(repo, token) as http:
        reply = http.get(f"/commits/{sha}").raise_for_status()
    return [item["sha"] for item in reply.json()["parents"]]


async def live_baseline(github: GitHubAppService, repo: str) -> RepoBaseline:
    """The baseline that matches the repository as it is now (what a decided run would have left)."""
    rulesets = await github.list_rulesets(repo)
    return RepoBaseline(
        repo=repo,
        rulesets=tuple(
            RulesetBaseline(ruleset_id=ruleset_id, digest=ruleset_digest(document))
            for ruleset_id, document in sorted(rulesets.items())
        ),
        protections=tuple(
            [
                ProtectionBaseline(
                    branch=branch,
                    digest=protection_digest(await github.read_branch_protection(repo, branch)),
                )
                for branch in GOVERNED
            ]
        ),
    )
