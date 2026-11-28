"""What the check posts, from plain values: faults, a lost second read, shared heads, paging.

These conditions (a 5xx, a rate limit, a change between the read and the post, a list over one
page) cannot be produced on demand against real GitHub, so the pure rules are tested directly.
"""

from datetime import UTC, datetime

import pytest

from src.engine.gates.gate_decision_rules import (
    PAGE_SIZE,
    failure_after_fault,
    next_page,
    not_recorded_for_recheck,
    outcome_after_recording,
    refusal_for,
    choose_rule,
    more_than_one_gate_label,
    MORE_THAN_ONE_GATE_LABEL,
    sharing_pulls,
    withdrawal_after_fault,
    withdrawal_for,
)
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import (
    Attestation,
    GateDecisionStateType,
    GateRule,
    OpenPull,
    SignoffAssessment,
    SignoffReading,
)

_HEAD = "a" * 40
_OTHER = "b" * 40
_OWN = PullRequestRef(repo="r", number=1)
_RULE = GateRule(label="spec-lgtm", branch="develop", rung=RungType.L2, holders=frozenset({"x"}))
_SIGNOFF = SignoffReading(
    signer="x",
    label="spec-lgtm",
    head_sha=_HEAD,
    signed_at=datetime(2026, 11, 27, tzinfo=UTC),
    attestation=Attestation(
        initiative="I",
        head=_HEAD,
        gate="spec-lgtm",
        repo="r",
        pull_request=1,
        digests=("c" * 64,),
        artifact_paths=("a.md",),
    ),
)
_SIGNED = SignoffAssessment(signoff=_SIGNOFF, reason=None)
_UNSIGNED = SignoffAssessment(signoff=None, reason="no Approve stands")


def _pull(
    number: int, head: str = _HEAD, base: str = "develop", labels: tuple[str, ...] = ()
) -> OpenPull:
    return OpenPull(
        ref=PullRequestRef(repo="r", number=number), base_ref=base, head_sha=head, labels=labels
    )


@pytest.mark.req("REQ-43")
def test_a_fault_after_the_head_is_known_is_a_failure_on_that_head() -> None:
    outcome = failure_after_fault(_HEAD, "GitHubError")
    assert outcome.state is GateDecisionStateType.FAILURE and outcome.head_sha == _HEAD
    assert "GitHubError" in outcome.reason


@pytest.mark.req("REQ-43")
def test_a_success_is_replaced_by_failure_when_the_second_read_lost_the_signoff() -> None:
    posted = outcome_after_recording(_HEAD, _RULE, _SIGNOFF, True)
    assert posted.state is GateDecisionStateType.SUCCESS
    assert withdrawal_for(posted, _HEAD, _SIGNED) is None
    lost = withdrawal_for(posted, _HEAD, _UNSIGNED)
    assert lost is not None and lost.state is GateDecisionStateType.FAILURE
    moved = withdrawal_for(posted, _OTHER, _SIGNED)
    assert moved is not None and moved.state is GateDecisionStateType.FAILURE
    faulted = withdrawal_after_fault(posted, "GitHubError")
    assert faulted.state is GateDecisionStateType.FAILURE


@pytest.mark.req("REQ-43")
def test_success_needs_the_decision_in_the_ledger() -> None:
    assert outcome_after_recording(_HEAD, _RULE, _SIGNOFF, False).state is (
        GateDecisionStateType.FAILURE
    )


@pytest.mark.req("REQ-63")
def test_only_other_open_governed_pull_requests_with_this_exact_head_share_it() -> None:
    candidates = [
        _pull(1),
        _pull(2, head=_OTHER),
        _pull(3),
        _pull(4, base="scratch"),
    ]
    shared = sharing_pulls(candidates, _HEAD, _OWN)
    assert [p.ref.number for p in shared] == [3]
    assert refusal_for(_HEAD, _SIGNED, ()) is None
    refused = refusal_for(_HEAD, _SIGNED, shared)
    assert refused is not None and "#3" in refused.reason
    assert refusal_for(_HEAD, _UNSIGNED, ()) is not None


@pytest.mark.req("REQ-63")
def test_a_list_longer_than_a_page_is_read_to_its_end_and_finds_the_sharing_pull_on_page_two() -> (
    None
):
    page_one = [_pull(n, head=_OTHER) for n in range(10, 10 + PAGE_SIZE)]
    page_two = [_pull(500)]
    pages = [page_one, page_two]
    seen: list[OpenPull] = []
    page: int | None = 1
    while page is not None:
        batch = pages[page - 1]
        seen += batch
        page = next_page(page, len(batch))
    assert len(seen) == PAGE_SIZE + 1
    assert [p.ref.number for p in sharing_pulls(seen, _HEAD, _OWN)] == [500]
    assert next_page(1, PAGE_SIZE - 1) is None


_DESIGN = GateRule(
    label="design-lgtm", branch="develop", rung=RungType.L2, holders=frozenset({"x"})
)


@pytest.mark.req("REQ-63")
def test_a_pull_request_names_its_gate_only_by_exactly_one_label_of_its_branch() -> None:
    rules = [_RULE, _DESIGN]
    assert choose_rule(_pull(1, labels=("spec-lgtm",)), rules) == _RULE
    assert choose_rule(_pull(1, labels=("design-lgtm", "unrelated")), rules) == _DESIGN
    none = choose_rule(_pull(1), rules)
    assert not isinstance(none, GateRule) and "none of the gate labels" in none.reason
    other_branch = choose_rule(_pull(1, base="main", labels=("spec-lgtm",)), rules)
    assert not isinstance(other_branch, GateRule)
    two = choose_rule(_pull(1, labels=("spec-lgtm", "design-lgtm")), rules)
    assert not isinstance(two, GateRule)
    assert two.state is GateDecisionStateType.FAILURE and MORE_THAN_ONE_GATE_LABEL in two.reason
    assert more_than_one_gate_label(("spec-lgtm", "design-lgtm"), "develop", rules)
    assert not more_than_one_gate_label(("spec-lgtm", "design-lgtm"), "main", rules)


@pytest.mark.req("REQ-63")
def test_the_recheck_fails_a_gate_with_no_recorded_decision() -> None:
    outcome = not_recorded_for_recheck(_HEAD, _RULE)
    assert outcome.state is GateDecisionStateType.FAILURE and "spec-lgtm" in outcome.reason
