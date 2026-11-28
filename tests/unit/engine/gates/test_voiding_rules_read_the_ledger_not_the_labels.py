"""What voids a signoff, from plain values: the conditions the journeys cannot reach live.

Void label names come with the gate (the wave gate has its own), the stale baseline is what the
holder attested, a void needs a later signoff, and a no belongs to its decision and its holder.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import re

import pytest
from pydantic import ValidationError

from src.engine.gates.non_merge_rules import decision_role
from src.engine.gates.voiding_rules import (
    attested_upstream_heads,
    changed_upstreams,
    revised_label,
    approves_on_head,
    stale_approves_on_head,
    attestation_evidence,
    body_digest,
    pinned_digest,
    without_reviews,
    revised_role,
    signoff_is_voided,
    stale_role,
    voided_review_ids,
    review_evidence,
    stale_label,
    unresolved_no,
)
from src.models.gate_models import GateClassType, PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import (
    Attestation,
    AttestedUpstream,
    MANDATE_ACTOR,
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewerKindType,
    ReviewStateType,
    UpstreamHead,
)

_HEAD_A = "a" * 40
_HEAD_B = "b" * 40
_UPSTREAM = PullRequestRef(repo="mandate-sandbox-meta", number=7)
_NOW = datetime(2026, 11, 28, 9, 0, 0, tzinfo=UTC)


def _rule(label: str, revised: str | None = None, stale: str | None = None) -> GateRule:
    return GateRule(
        label=label,
        branch="develop",
        rung=RungType.L2,
        holders=frozenset({"x"}),
        revised_label=revised,
        stale_label=stale,
    )


def _attestation(upstream: tuple[AttestedUpstream, ...]) -> Attestation:
    return Attestation(
        initiative="INIT",
        head=_HEAD_A,
        gate="spec-lgtm",
        repo="r",
        pull_request=1,
        digests=("c" * 64,),
        artifact_paths=("p",),
        upstream=upstream,
    )


@pytest.mark.req("REQ-42")
@pytest.mark.parametrize(
    ("label", "revised", "stale"),
    [
        ("spec-lgtm", "spec-revised", "spec-stale"),
        ("impact-map-lgtm", "impact-map-revised", "impact-map-stale"),
        ("wave-accepted", "wave-revised", "wave-stale"),
        ("spec", "spec-revised", "spec-stale"),
        ("-lgtm", "-lgtm-revised", "-lgtm-stale"),
    ],
)
def test_the_void_labels_come_with_the_gate_and_no_label_shape_fails(
    label: str, revised: str, stale: str
) -> None:
    assert revised_label(_rule(label)) == revised
    assert stale_label(_rule(label)) == stale


@pytest.mark.req("REQ-42")
def test_a_gate_can_name_its_own_void_labels() -> None:
    rule = _rule("wave-accepted", revised="wave-redo", stale="wave-old")
    assert (revised_label(rule), stale_label(rule)) == ("wave-redo", "wave-old")


@pytest.mark.req("REQ-121")
def test_an_upstream_missing_from_the_attestation_or_attested_at_another_head_is_changed() -> None:
    attested = attested_upstream_heads(
        _attestation(
            (AttestedUpstream(repo=_UPSTREAM.repo, pull_request=_UPSTREAM.number, head=_HEAD_A),)
        )
    )
    now_a = [UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_A)]
    now_b = [UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_B)]
    assert changed_upstreams(attested, now_a) == ()
    assert changed_upstreams(attested, now_b) == tuple(now_b)
    assert changed_upstreams(attested_upstream_heads(_attestation(())), now_a) == tuple(now_a)


@pytest.mark.req("REQ-121")
def test_an_attested_upstream_with_an_extra_field_is_refused() -> None:
    with pytest.raises(ValidationError):
        AttestedUpstream.model_validate(
            {"repo": "r", "pull_request": 1, "head": _HEAD_A, "note": "x"}
        )


@pytest.mark.req("REQ-42")
def test_an_approve_named_by_a_void_does_not_count_and_a_new_one_does() -> None:
    voided = voided_review_ids(review_evidence((11, 12)))
    assert voided == frozenset({11, 12})
    assert signoff_is_voided(11, voided) is True
    assert signoff_is_voided(13, voided) is False
    assert voided_review_ids(()) == frozenset()


@pytest.mark.req("REQ-42")
def test_void_roles_follow_the_gates_own_label_not_its_display_labels() -> None:
    plain = _rule("spec-lgtm")
    renamed = _rule("spec-lgtm", revised="spec-redo", stale="spec-old")
    short = _rule("spec")
    assert revised_role(plain) == revised_role(renamed) == "spec-lgtm revised"
    assert stale_role(plain) == stale_role(renamed) == "spec-lgtm stale"
    assert revised_role(short) != revised_role(plain)


@pytest.mark.req("REQ-42")
def test_no_github_login_can_be_taken_for_mandate() -> None:
    login = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$")
    assert login.fullmatch(MANDATE_ACTOR) is None
    for account in ("mandate", "Mandate", "mandate[bot]", "mandate-app"):
        assert account != MANDATE_ACTOR


def _review(review_id: int, who: str, head: str, state: ReviewStateType) -> PullReview:
    return PullReview(
        review_id=review_id,
        reviewer=who,
        reviewer_kind=ReviewerKindType.USER,
        state=state,
        commit_id=head,
        body="b",
        submitted_at=_NOW + timedelta(seconds=review_id),
        edited=False,
    )


def _snapshot(reviews: tuple[PullReview, ...]) -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=PullRequestRef(repo="r", number=1),
        base_ref="develop",
        head_sha=_HEAD_A,
        labels=("spec-lgtm",),
        is_draft=False,
        reviews=reviews,
    )


@pytest.mark.req("REQ-42")
def test_a_void_names_every_approve_on_the_head_by_any_reviewer() -> None:
    snapshot = _snapshot(
        (
            _review(1, "holder-a", _HEAD_A, ReviewStateType.DISMISSED),
            _review(2, "holder-b", _HEAD_A, ReviewStateType.APPROVED),
            _review(3, "holder-b", _HEAD_B, ReviewStateType.APPROVED),
            _review(4, "holder-c", _HEAD_A, ReviewStateType.COMMENTED),
        )
    )
    assert approves_on_head(snapshot, _HEAD_A) == (1, 2)
    left = without_reviews(snapshot, frozenset({1, 2}))
    assert [review.review_id for review in left.reviews] == [3, 4]


@pytest.mark.req("REQ-40")
def test_the_pinned_digest_is_the_hash_of_the_exact_body() -> None:
    body = "attestation:\n  head: x\n"
    evidence = attestation_evidence(7, body_digest(body))
    assert pinned_digest(evidence) == body_digest(body)
    assert pinned_digest(attestation_evidence(7, body_digest(body + " "))) != body_digest(body)
    assert pinned_digest(()) is None


@pytest.mark.req("REQ-121")
def test_the_newest_recorded_decision_on_the_artifact_decides_whether_a_no_stands() -> None:
    assert unresolved_no([None, "request_changes", "approve"]) is True
    assert unresolved_no(["approve", "request_changes"]) is False
    assert unresolved_no([None, None]) is False


@pytest.mark.req("REQ-121")
def test_a_decision_is_recorded_under_a_role_that_names_its_own_gate() -> None:
    first, second = uuid4(), uuid4()
    assert decision_role(GateClassType.VERIFICATION, first) != decision_role(
        GateClassType.VERIFICATION, second
    )
    assert decision_role(GateClassType.VERIFICATION, first).startswith("verification decision ")


def _attesting(review_id: int, upstream_head: str) -> PullReview:
    body = (
        f"attestation:\n  initiative: I\n  head: {_HEAD_A}\n  gate: spec-lgtm\n  repo: r\n"
        f"  pull_request: 1\n  digests: ['{'c' * 64}']\n  artifact_paths: [p]\n"
        f"  upstream:\n    - repo: {_UPSTREAM.repo}\n      pull_request: {_UPSTREAM.number}\n"
        f"      head: {upstream_head}\n"
    )
    return _review(review_id, "holder", _HEAD_A, ReviewStateType.APPROVED).model_copy(
        update={"body": body}
    )


@pytest.mark.req("REQ-121")
def test_a_stale_void_names_only_approves_not_given_against_the_current_upstream() -> None:
    snapshot = _snapshot(
        (
            _attesting(1, _HEAD_A),
            _attesting(2, _HEAD_B),
            _review(3, "holder-c", _HEAD_A, ReviewStateType.APPROVED),
        )
    )
    now = [UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_B)]
    # 1 attests the old head, 2 the current one, 3 is not a readable attestation.
    assert stale_approves_on_head(snapshot, now) == (1, 3)
