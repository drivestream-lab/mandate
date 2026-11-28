"""What voids a signoff, from plain values: the conditions the journeys cannot reach live.

A gate label without -lgtm, an upstream that was never recorded, and a recorded no that a later
decision on an earlier head must not undo are decided by the pure rules.
"""

import pytest

from src.engine.gates.voiding_rules import (
    GateLabelNameError,
    changed_upstreams,
    heads_signed_against,
    revised_label,
    stale_label,
    unresolved_no,
    upstream_evidence,
)
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType
from src.models.signoff_models import GateRule, UpstreamHead

_HEAD_A = "a" * 40
_HEAD_B = "b" * 40
_UPSTREAM = PullRequestRef(repo="mandate-sandbox-meta", number=7)


def _rule(label: str) -> GateRule:
    return GateRule(label=label, branch="develop", rung=RungType.L2, holders=frozenset({"x"}))


@pytest.mark.req("REQ-42")
def test_the_void_labels_follow_the_gate_label() -> None:
    assert revised_label(_rule("spec-lgtm")) == "spec-revised"
    assert stale_label(_rule("impact-map-lgtm")) == "impact-map-stale"


@pytest.mark.req("REQ-42")
@pytest.mark.parametrize("label", ["spec", "-lgtm", "spec-approved"])
def test_a_gate_label_without_the_lgtm_suffix_has_no_void_labels(label: str) -> None:
    with pytest.raises(GateLabelNameError):
        revised_label(_rule(label))


@pytest.mark.req("REQ-121")
def test_an_upstream_head_never_recorded_or_different_counts_as_changed() -> None:
    recorded = heads_signed_against(
        upstream_evidence([UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_A)])
    )
    assert changed_upstreams(recorded, [UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_A)]) == ()
    now = [UpstreamHead(upstream=_UPSTREAM, head_sha=_HEAD_B)]
    assert changed_upstreams(recorded, now) == tuple(now)
    assert changed_upstreams({}, now) == tuple(now)


@pytest.mark.req("REQ-121")
def test_the_newest_recorded_decision_on_the_artifact_decides_whether_a_no_stands() -> None:
    assert unresolved_no([None, "request_changes", "approve"]) is True
    assert unresolved_no(["approve", "request_changes"]) is False
    assert unresolved_no([None, None]) is False
