"""A signoff is the gate's label, an attested Approve on the head and a ready pull request."""

from datetime import UTC, datetime, timedelta

import pytest

from src.engine.gates.signoff_rules import assess_signoff, read_attestation
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import (
    Attestation,
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewerKindType,
    ReviewStateType,
)

_HEAD = "a" * 40
_OLD = "b" * 40
_T0 = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
_PERSON = "holder"
_BOT = "holder[bot]"
_L0 = GateRule(label="spec-lgtm", branch="develop", rung=RungType.L0, holders=frozenset({_PERSON}))
_L2 = GateRule(label="spec-lgtm", branch="develop", rung=RungType.L2, holders=frozenset({_BOT}))


def _body(head: str = _HEAD, gate: str = "spec-lgtm", number: int = 1, repo: str = "r") -> str:
    return (
        "attestation:\n"
        f"  initiative: INIT-X\n  head: {head}\n  gate: {gate}\n  repo: {repo}\n"
        f"  pull_request: {number}\n  digests: ['{'c' * 64}']\n  artifact_paths: [spec.md]\n"
    )


def _review(
    who: str = _PERSON,
    kind: ReviewerKindType = ReviewerKindType.USER,
    state: ReviewStateType = ReviewStateType.APPROVED,
    commit: str = _HEAD,
    body: str | None = None,
    at: datetime = _T0,
) -> PullReview:
    return PullReview(
        review_id=1,
        reviewer=who,
        reviewer_kind=kind,
        state=state,
        commit_id=commit,
        body=_body(commit) if body is None else body,
        submitted_at=at,
        edited=False,
    )


def _snapshot(
    reviews: tuple[PullReview, ...] = (),
    labels: tuple[str, ...] = ("spec-lgtm",),
    draft: bool = False,
    base: str = "develop",
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=PullRequestRef(repo="r", number=1),
        base_ref=base,
        head_sha=_HEAD,
        labels=labels,
        is_draft=draft,
        reviews=reviews,
    )


@pytest.mark.req("REQ-40")
def test_label_attested_approve_and_ready_from_the_holder_is_a_signoff() -> None:
    result = assess_signoff(_snapshot((_review(),)), _L0)
    assert result.signoff is not None and result.signoff.signer == _PERSON
    assert result.reason is None


@pytest.mark.req("REQ-40")
@pytest.mark.parametrize(
    ("snapshot", "fragment"),
    [
        (_snapshot((_review(),), labels=()), "label"),
        (_snapshot((_review(),), draft=True), "not marked ready"),
        (_snapshot((_review(),), base="main"), "merges into main"),
        (_snapshot(()), "no Approve"),
        (_snapshot((_review(commit=_OLD),)), "no Approve"),
        (_snapshot((_review(body="looks good"),)), "no attestation"),
        (_snapshot((_review(body=_body(_OLD)),)), "another head"),
        (_snapshot((_review(body=_body(gate="design-lgtm")),)), "another head, gate"),
        (_snapshot((_review(body=_body(number=2)),)), "pull request"),
        (_snapshot((_review(body=_body(repo="other")),)), "repository"),
        (_snapshot((_review(who="someone"),)), "does not hold"),
    ],
)
def test_any_missing_or_mismatched_part_is_refused_with_its_reason(
    snapshot: PullRequestSnapshot, fragment: str
) -> None:
    result = assess_signoff(snapshot, _L0)
    assert result.signoff is None
    assert result.reason is not None and fragment in result.reason


@pytest.mark.req("REQ-40")
def test_an_attestation_missing_a_field_names_it() -> None:
    body = "attestation:\n  initiative: INIT-X\n  head: " + _HEAD + "\n  gate: spec-lgtm\n"
    reason = read_attestation(body)
    assert isinstance(reason, str)
    for name in ("digests", "artifact_paths", "repo", "pull_request"):
        assert name in reason


@pytest.mark.req("REQ-40")
def test_an_attestation_with_an_extra_field_is_refused() -> None:
    reason = read_attestation(_body() + "  note: extra\n")
    assert isinstance(reason, str) and "note" in reason
    assert isinstance(read_attestation(_body()), Attestation)


@pytest.mark.req("REQ-40")
def test_an_app_cannot_decide_an_l0_gate_but_can_at_l2() -> None:
    app_review = _review(who=_BOT, kind=ReviewerKindType.BOT)
    l0_rule = GateRule(
        label="spec-lgtm", branch="develop", rung=RungType.L0, holders=frozenset({_BOT})
    )
    refused = assess_signoff(_snapshot((app_review,)), l0_rule)
    assert refused.signoff is None
    assert refused.reason is not None and "decided by a person" in refused.reason
    assert assess_signoff(_snapshot((app_review,)), _L2).signoff is not None


@pytest.mark.req("REQ-40")
def test_the_authors_label_and_ready_with_the_holders_approve_pass_and_without_it_fail() -> None:
    # Whoever applied the label or marked ready is not part of the decision.
    assert assess_signoff(_snapshot((_review(),)), _L0).signoff is not None
    assert assess_signoff(_snapshot(()), _L0).signoff is None


@pytest.mark.req("REQ-43")
def test_a_gate_nobody_signed_never_passes_however_long_it_waits() -> None:
    later = _snapshot((_review(state=ReviewStateType.COMMENTED, at=_T0 + timedelta(days=30)),))
    assert assess_signoff(later, _L0).signoff is None


@pytest.mark.req("REQ-43")
def test_a_later_changes_request_or_dismissal_withdraws_the_approve() -> None:
    for state in (ReviewStateType.CHANGES_REQUESTED, ReviewStateType.DISMISSED):
        later = _review(state=state, at=_T0 + timedelta(minutes=1))
        assert assess_signoff(_snapshot((_review(), later)), _L0).signoff is None
