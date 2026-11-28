"""The check fails on any fault once the head is known, and withdraws success that no longer holds.

The GitHub client here is a fake at the infra boundary: these faults (a 5xx, a rate limit, a
revocation between the read and the post) cannot be produced on demand against real GitHub.
"""

from datetime import UTC, datetime

import pytest

from src.business_services.gates.gate_decision_check_service import (
    GateDecisionCheckService,
    GateUnreadableError,
)
from src.business_services.gates.signoff_service import SignoffService
from src.infra_services.github_app_service import GitHubError
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import RungType, StoredLedgerEntry
from src.models.signoff_models import (
    GateDecisionStateType,
    GateRule,
    OpenPull,
    PullRequestSnapshot,
    PullReview,
    ReviewerKindType,
    ReviewStateType,
    SignoffReading,
)

_HEAD = "a" * 40
_REF = PullRequestRef(repo="r", number=1)
_RULE = GateRule(
    label="spec-lgtm", branch="develop", rung=RungType.L2, holders=frozenset({"b[bot]"})
)
_STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="g", version="1"),),
    skills=(NamedVersion(name="s", version="1"),),
    rules="r",
    agent_setup="a",
    policy_revision="p",
    mandate_release="0",
)
_BODY = (
    "attestation:\n  initiative: I\n  head: " + _HEAD + "\n  gate: spec-lgtm\n  repo: r\n"
    "  pull_request: 1\n  digests: ['" + "c" * 64 + "']\n  artifact_paths: [a.md]\n"
)


def _snapshot(approved: bool = True) -> PullRequestSnapshot:
    review = PullReview(
        review_id=1,
        reviewer="b[bot]",
        reviewer_kind=ReviewerKindType.BOT,
        state=ReviewStateType.APPROVED if approved else ReviewStateType.DISMISSED,
        commit_id=_HEAD,
        body=_BODY,
        submitted_at=datetime(2026, 11, 27, tzinfo=UTC),
    )
    return PullRequestSnapshot(
        ref=_REF,
        base_ref="develop",
        head_sha=_HEAD,
        labels=("spec-lgtm",),
        is_draft=False,
        reviews=(review,),
    )


class _Github:
    """Answers reads from a script; each entry is a snapshot or the error to raise."""

    def __init__(
        self,
        reads: list[PullRequestSnapshot | GitHubError],
        head: str | GitHubError = _HEAD,
        pulls: tuple[OpenPull, ...] = (),
    ) -> None:
        self._reads = reads
        self._head = head
        self._pulls = pulls
        self.posted: list[tuple[GateDecisionStateType, str]] = []

    async def read_pull_request(self, ref: PullRequestRef) -> PullRequestSnapshot:
        item = self._reads.pop(0)
        if isinstance(item, GitHubError):
            raise item
        return item

    async def read_head_sha(self, ref: PullRequestRef) -> str:
        if isinstance(self._head, GitHubError):
            raise self._head
        return self._head

    async def open_pulls_for_commit(self, repo: str, head_sha: str) -> tuple[OpenPull, ...]:
        return self._pulls

    async def post_gate_decision(
        self, repo: str, head_sha: str, state: GateDecisionStateType, description: str
    ) -> None:
        self.posted.append((state, description))


class _Signoffs(SignoffService):
    """A signoff service whose ledger always accepts."""

    def __init__(self) -> None:  # no ledger: recording is the fake's job here
        pass

    async def is_recorded(self, signoff: SignoffReading, rule: GateRule) -> bool:
        return True

    async def record_signoff(
        self, signoff: SignoffReading, rule: GateRule, stamp: VersionStamp
    ) -> StoredLedgerEntry | None:
        return None


def _service() -> GateDecisionCheckService:
    return GateDecisionCheckService(_Signoffs())


@pytest.mark.req("REQ-43")
async def test_a_read_error_after_the_head_is_known_posts_failure() -> None:
    github = _Github([GitHubError("GitHub answered 502")])
    outcome = await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert outcome.state is GateDecisionStateType.FAILURE
    assert github.posted[0][0] is GateDecisionStateType.FAILURE


@pytest.mark.req("REQ-43")
async def test_a_pull_request_that_cannot_be_read_at_all_is_raised_not_passed() -> None:
    github = _Github([], head=GitHubError("GitHub answered 502"))
    with pytest.raises(GateUnreadableError):
        await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert github.posted == []


@pytest.mark.req("REQ-43")
async def test_success_is_withdrawn_when_the_signoff_is_gone_on_the_second_read() -> None:
    github = _Github([_snapshot(), _snapshot(approved=False)])
    outcome = await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert [state for state, _ in github.posted] == [
        GateDecisionStateType.SUCCESS,
        GateDecisionStateType.FAILURE,
    ]
    assert outcome.state is GateDecisionStateType.FAILURE


@pytest.mark.req("REQ-43")
async def test_success_is_withdrawn_when_the_second_read_fails() -> None:
    github = _Github([_snapshot(), GitHubError("rate limited")])
    outcome = await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert outcome.state is GateDecisionStateType.FAILURE


@pytest.mark.req("REQ-63")
async def test_another_open_pull_request_into_a_governed_branch_on_the_head_fails() -> None:
    other = OpenPull(ref=PullRequestRef(repo="r", number=2), base_ref="main")
    github = _Github([_snapshot()], pulls=(other,))
    outcome = await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert outcome.state is GateDecisionStateType.FAILURE and "#2" in outcome.reason


@pytest.mark.req("REQ-63")
async def test_a_clean_signoff_passes_and_stays_passed_when_it_still_holds() -> None:
    github = _Github([_snapshot(), _snapshot()])
    outcome = await _service().evaluate_and_post(github, _REF, _RULE, _STAMP)
    assert outcome.state is GateDecisionStateType.SUCCESS
    assert [state for state, _ in github.posted] == [GateDecisionStateType.SUCCESS]
