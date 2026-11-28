"""Mandate signs and merges only at L2 and L3, and only for the head the attestation names.

The pure rules that decide it: at L0 and L1 a person signs and the merger merges, so Mandate
applies nothing; at L2 and L3 the attestation must name this head, gate, repository and pull
request, and the Approve body Mandate writes is read back by the check as a complete attestation.
The merge itself is exercised against GitHub in the journeys (a sha-pinned merge cannot be
produced without a real head).
"""

import pytest

from src.engine.gates.merge_rules import (
    LEFT_TO_MERGER,
    attestation_body,
    mandate_merges,
    signoff_problem,
)
from src.engine.gates.signoff_rules import read_attestation
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import Attestation, GateRule, PullRequestSnapshot

_HEAD = "a" * 40
_OTHER = "b" * 40


def _rule(rung: RungType) -> GateRule:
    return GateRule(
        label="wave-accepted", branch="develop", rung=rung, holders=frozenset({"app[bot]"})
    )


def _attestation(
    head: str = _HEAD, gate: str = "wave-accepted", repo: str = "svc", pull: int = 7
) -> Attestation:
    return Attestation(
        initiative="INIT-X",
        head=head,
        gate=gate,
        repo=repo,
        pull_request=pull,
        digests=("c" * 64,),
        artifact_paths=("wave.md",),
    )


def _snapshot(head: str = _HEAD, base: str = "develop") -> PullRequestSnapshot:
    return PullRequestSnapshot(
        ref=PullRequestRef(repo="svc", number=7),
        base_ref=base,
        head_sha=head,
        labels=(),
        is_draft=True,
        reviews=(),
    )


@pytest.mark.req("REQ-63")
@pytest.mark.parametrize("rung", [RungType.L0, RungType.L1])
def test_a_person_signs_and_the_merger_merges_below_l2(rung: RungType) -> None:
    assert mandate_merges(rung) is False
    assert signoff_problem(_snapshot(), _rule(rung), _attestation()) == LEFT_TO_MERGER


@pytest.mark.req("REQ-63")
@pytest.mark.parametrize("rung", [RungType.L2, RungType.L3])
def test_mandate_applies_a_matching_signoff_at_l2_and_l3(rung: RungType) -> None:
    assert mandate_merges(rung) is True
    assert signoff_problem(_snapshot(), _rule(rung), _attestation()) is None


@pytest.mark.req("REQ-63")
@pytest.mark.parametrize(
    ("snapshot", "attestation", "fragment"),
    [
        (_snapshot(head=_OTHER), _attestation(), "another head"),
        (_snapshot(), _attestation(gate="spec-lgtm"), "gate spec-lgtm"),
        (_snapshot(), _attestation(repo="other"), "another repository"),
        (_snapshot(), _attestation(pull=8), "another repository or pull request"),
        (_snapshot(base="main"), _attestation(), "merges into main"),
    ],
)
def test_an_attestation_for_anything_else_is_not_applied(
    snapshot: PullRequestSnapshot, attestation: Attestation, fragment: str
) -> None:
    problem = signoff_problem(snapshot, _rule(RungType.L2), attestation)
    assert problem is not None and fragment in problem


@pytest.mark.req("REQ-63")
def test_the_approve_body_is_read_back_as_the_same_attestation() -> None:
    attestation = _attestation()
    assert read_attestation(attestation_body(attestation)) == attestation
