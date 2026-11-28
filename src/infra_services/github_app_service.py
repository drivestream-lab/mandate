"""Mandate's client for GitHub, acting as Mandate's App and nothing else.

It reads pull requests (head, labels, ready state, reviews), posts the required check
mandate/gate-decision on a head, and posts a brief or a review request on a pull request. It
never applies a label, approves, marks ready or merges: those belong to the signer. A response
that does not fit the expected shape raises; nothing is guessed.
"""

import time
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import quote

import httpx
from injector import NoInject, inject
from jose import jwt
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from src.configs.github_app_settings import GitHubAppSettings
from src.engine.gates.gate_decision_rules import PAGE_SIZE, next_page
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.gate_models import PullRequestRef
from src.models.signoff_models import (
    GATE_DECISION_CONTEXT,
    GateDecisionStateType,
    OpenPull,
    PullRequestSnapshot,
    PullReview,
    ReviewerKindType,
    ReviewStateType,
)

logger = get_logger()

_TOKEN_REUSE_SECONDS = 50 * 60
_STATUS_DESCRIPTION_LIMIT = 140
_READ_ATTEMPTS = 3
"""Reads and the check status (same state, same effect) are repeated after a dropped
connection or a 5xx; comments and reviews never are."""


class GitHubError(Exception):
    """GitHub refused a call or answered in a shape Mandate does not recognise."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Token(_Record):
    token: str

    def __repr__(self) -> str:
        return "_Token(<redacted>)"


class _Head(_Record):
    sha: str


class _Label(_Record):
    name: str


class _Base(_Record):
    ref: str


class _Pull(_Record):
    head: _Head
    base: _Base
    draft: bool
    labels: list[_Label]


class _User(_Record):
    login: str
    type: ReviewerKindType


class _Review(_Record):
    id: int
    user: _User | None
    state: ReviewStateType
    commit_id: str | None
    body: str | None
    submitted_at: datetime | None


class _ListedPull(_Record):
    number: int
    base: _Base
    head: _Head
    labels: list[_Label]


_REVIEWS = TypeAdapter(list[_Review])
_OPEN_PULLS = TypeAdapter(list[_ListedPull])


class GitHubAppService(BaseInfraService):
    """GitHub as Mandate's App."""

    @inject
    def __init__(self, settings: NoInject[GitHubAppSettings | None] = None) -> None:
        self._settings = settings if settings is not None else GitHubAppSettings.get_instance()
        self._client: httpx.AsyncClient | None = None
        self._token: str | None = None
        self._token_at = 0.0

    async def initialize(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._settings.api_url.rstrip("/"),
                timeout=self._settings.request_timeout_seconds,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._token = None

    async def health_check(self) -> bool:
        try:
            await self._token_for_calls()
        except (GitHubError, OSError, httpx.HTTPError):
            return False
        return True

    async def read_pull_request(self, ref: PullRequestRef) -> PullRequestSnapshot:
        """The pull request's head, labels, ready state and every review."""
        base = f"/repos/{self._settings.owner}/{ref.repo}/pulls/{ref.number}"
        pull = self._parse(_Pull, await self._get(base))
        reviews: list[_Review] = []
        page = 1
        while True:
            response = await self._get(f"{base}/reviews", {"per_page": PAGE_SIZE, "page": page})
            try:
                batch = _REVIEWS.validate_json(response.content)
            except ValidationError as error:
                raise GitHubError(f"unexpected reviews answer for {base}") from error
            reviews += batch
            if len(batch) < PAGE_SIZE:
                break
            page += 1
        return PullRequestSnapshot(
            ref=ref,
            base_ref=pull.base.ref,
            head_sha=pull.head.sha,
            labels=tuple(label.name for label in pull.labels),
            is_draft=pull.draft,
            reviews=tuple(_to_review(item) for item in reviews),
        )

    async def read_head_sha(self, ref: PullRequestRef) -> str:
        """Only the pull request's head commit (when the rest of it cannot be read)."""
        path = f"/repos/{self._settings.owner}/{ref.repo}/pulls/{ref.number}"
        return self._parse(_Pull, await self._get(path)).head.sha

    async def list_open_pulls(self, repo: str, base: str) -> tuple[OpenPull, ...]:
        """Every open pull request into this branch, fork pull requests included."""
        path = f"/repos/{self._settings.owner}/{repo}/pulls"
        found: list[OpenPull] = []
        page: int | None = 1
        while page is not None:
            params: dict[str, int | str] = {
                "state": "open", "base": base, "per_page": PAGE_SIZE, "page": page,
            }  # fmt: skip
            try:
                batch = _OPEN_PULLS.validate_json((await self._get(path, params)).content)
            except ValidationError as error:
                raise GitHubError(f"unexpected answer for {path}") from error
            found += [
                OpenPull(
                    ref=PullRequestRef(repo=repo, number=item.number),
                    base_ref=item.base.ref,
                    head_sha=item.head.sha,
                    labels=tuple(label.name for label in item.labels),
                )
                for item in batch
            ]
            page = next_page(page, len(batch))
        return tuple(found)

    async def post_gate_decision(
        self, repo: str, head_sha: str, state: GateDecisionStateType, description: str
    ) -> None:
        """Post mandate/gate-decision on a head commit."""
        path = f"/repos/{self._settings.owner}/{repo}/statuses/{head_sha}"
        body = {
            "state": state.value,
            "context": GATE_DECISION_CONTEXT,
            "description": description[:_STATUS_DESCRIPTION_LIMIT],
        }
        await self._post(path, body, repeatable=True)

    async def add_label(self, ref: PullRequestRef, label: str) -> None:
        """Put a label on a pull request (adding one that is already there changes nothing)."""
        repo = f"/repos/{self._settings.owner}/{ref.repo}"
        await self._post(f"{repo}/issues/{ref.number}/labels", {"labels": [label]}, repeatable=True)

    async def remove_label(self, ref: PullRequestRef, label: str) -> None:
        """Take a label off a pull request. Not repeated: a second attempt would find it gone."""
        repo = f"/repos/{self._settings.owner}/{ref.repo}"
        path = f"{repo}/issues/{ref.number}/labels/{quote(label, safe='')}"
        self._raise_for_status(await self._send("DELETE", path, None, None, False), path)

    async def post_brief(self, pull_request: PullRequestRef, body: str) -> None:
        """Post a gate's brief as a comment on its pull request."""
        repo = f"/repos/{self._settings.owner}/{pull_request.repo}"
        await self._post(f"{repo}/issues/{pull_request.number}/comments", {"body": body})

    async def post_review_request(self, pull_request: PullRequestRef, body: str) -> None:
        """Ask for a decision as a review on the pull request (a comment review, no verdict)."""
        repo = f"/repos/{self._settings.owner}/{pull_request.repo}"
        await self._post(
            f"{repo}/pulls/{pull_request.number}/reviews", {"event": "COMMENT", "body": body}
        )

    async def _token_for_calls(self) -> str:
        if self._token is not None and time.monotonic() - self._token_at < _TOKEN_REUSE_SECONDS:
            return self._token
        client = self._ready()
        now = int(time.time())
        app_jwt = jwt.encode(
            {
                "iat": now - 60,
                "exp": now + 540,
                "iss": self._settings.app_id_file.read_text(encoding="utf-8").strip(),
            },
            self._settings.private_key_file.read_text(encoding="utf-8"),
            algorithm="RS256",
        )
        installation = self._settings.installation_id_file.read_text(encoding="utf-8").strip()
        response = await client.post(
            f"/app/installations/{installation}/access_tokens", headers=_headers(app_jwt)
        )
        self._raise_for_status(response, "installation token")
        self._token = self._parse(_Token, response).token
        self._token_at = time.monotonic()
        return self._token

    async def _get(self, path: str, params: dict[str, int | str] | None = None) -> httpx.Response:
        response = await self._send("GET", path, params, None, True)
        self._raise_for_status(response, path)
        return response

    async def _post(
        self, path: str, body: Mapping[str, str | list[str]], repeatable: bool = False
    ) -> None:
        self._raise_for_status(await self._send("POST", path, None, body, repeatable), path)

    async def _send(
        self,
        method: str,
        path: str,
        params: dict[str, int | str] | None,
        body: Mapping[str, str | list[str]] | None,
        repeatable: bool,
    ) -> httpx.Response:
        """One call; a repeatable one is tried again after a dropped connection or a 5xx."""
        attempts = _READ_ATTEMPTS if repeatable else 1
        error: httpx.HTTPError | None = None
        response: httpx.Response | None = None
        for _ in range(attempts):
            try:
                response = await self._ready().request(
                    method,
                    path,
                    params=params,
                    json=body,
                    headers=_headers(await self._token_for_calls()),
                )
            except httpx.TransportError as caught:
                error, response = caught, None
                continue
            if response.status_code < 500:
                return response
        if response is not None:
            return response
        raise GitHubError(f"GitHub could not be reached for {path}") from error

    def _ready(self) -> httpx.AsyncClient:
        if self._client is None:
            raise GitHubError("the GitHub client is not initialised")
        return self._client

    @staticmethod
    def _raise_for_status(response: httpx.Response, path: str) -> None:
        if not response.is_success:
            raise GitHubError(f"GitHub answered {response.status_code} for {path}")

    @staticmethod
    def _parse[M: BaseModel](model: type[M], response: httpx.Response) -> M:
        try:
            return model.model_validate_json(response.content)
        except ValidationError as error:
            raise GitHubError("unexpected answer from GitHub") from error


def _to_review(item: _Review) -> PullReview:
    if item.user is None or item.commit_id is None or item.submitted_at is None:
        raise GitHubError("a review is missing its reviewer, commit or time")
    return PullReview(
        review_id=item.id,
        reviewer=item.user.login,
        reviewer_kind=item.user.type,
        state=item.state,
        commit_id=item.commit_id,
        body=item.body or "",
        submitted_at=item.submitted_at,
    )


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
