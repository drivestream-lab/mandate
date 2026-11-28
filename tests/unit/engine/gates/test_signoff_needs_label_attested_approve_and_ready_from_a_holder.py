"""A signoff is the gate's label, an attested Approve on the head and a ready pull request."""

from datetime import UTC, datetime, timedelta

import pytest

from src.engine.gates.signoff_rules import assess_signoff, read_attestation
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import (
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewStateType,
)

_HEAD = "a" * 40
_OLD = "b" * 40
_T0 = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
_RULE = GateRule(label="spec-lgtm", rung=RungType.L0, holders=frozenset({"holder[bot]"}))


def _body(head: str = _HEAD, gate: str = "spec-lgtm") -> str:
    return f"attestation:\n  initiative: INIT-X\n  head: {head}\n  gate: {gate}\n"


def _review(
    who: str = "holder[bot]",
    state: ReviewStateType = ReviewStateType.APPROVED,
    commit: str = _HEAD,
    body: str | None = None,
    at: datetime = _T0,
) -> PullReview:
    return PullReview(
        reviewer=who,
        state=state,
        commit_id=commit,
        body=_body(commit) if body is None else body,
        submitted_at=at,
    )


def _snapshot(
    reviews: tuple[PullReview, ...] = (),
    labels: tuple[str, ...] = ("spec-lgtm",),
    draft: bool = False,
) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=PullRequestRef(repo="r", number=1),
        head_sha=_HEAD,
        labels=labels,
        is_draft=draft,
        reviews=reviews,
    )


@pytest.mark.req("REQ-40")
def test_label_attested_approve_and_ready_from_the_holder_is_a_signoff() -> None:
    result = assess_signoff(_snapshot((_review(),)), _RULE)
    assert result.signoff is not None and result.signoff.signer == "holder[bot]"
    assert result.reason is None


@pytest.mark.req("REQ-40")
@pytest.mark.parametrize(
    ("snapshot", "fragment"),
    [
        (_snapshot((_review(),), labels=()), "label"),
        (_snapshot((_review(),), draft=True), "not marked ready"),
        (_snapshot(()), "no Approve"),
        (_snapshot((_review(commit=_OLD),)), "no Approve"),
        (_snapshot((_review(body="looks good"),)), "attestation"),
        (_snapshot((_review(body=_body(_OLD)),)), "attestation"),
        (_snapshot((_review(body=_body(gate="design-lgtm")),)), "attestation"),
        (_snapshot((_review(who="someone"),)), "does not hold"),
    ],
)
def test_any_missing_or_mismatched_part_is_refused_with_its_reason(
    snapshot: PullRequestSnapshot, fragment: str
) -> None:
    result = assess_signoff(snapshot, _RULE)
    assert result.signoff is None
    assert result.reason is not None and fragment in result.reason


@pytest.mark.req("REQ-43")
def test_a_gate_nobody_signed_never_passes_however_long_it_waits() -> None:
    later = _snapshot((_review(state=ReviewStateType.COMMENTED, at=_T0 + timedelta(days=30)),))
    assert assess_signoff(later, _RULE).signoff is None


@pytest.mark.req("REQ-43")
def test_a_later_changes_request_or_dismissal_withdraws_the_approve() -> None:
    for state in (ReviewStateType.CHANGES_REQUESTED, ReviewStateType.DISMISSED):
        later = _review(state=state, at=_T0 + timedelta(minutes=1))
        assert assess_signoff(_snapshot((_review(), later)), _RULE).signoff is None


@pytest.mark.req("REQ-40")
def test_an_attestation_that_is_not_the_expected_shape_reads_as_none() -> None:
    assert read_attestation("attestation: [1, 2]") is None
    assert read_attestation(": : :") is None
    assert read_attestation("note: hi") is None
