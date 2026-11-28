"""A wave's check fails with the evidence's own reason, and a pass names the run it relied on."""

import pytest

from src.engine.gates.gate_decision_rules import (
    evidence_failure,
    evidence_repository_failure,
    wave_without_evidence,
    with_evidence,
)
from src.models.ledger_models import RungType
from src.models.signoff_models import GateDecisionOutcome, GateDecisionStateType, GateRule

_HEAD = "a" * 40


@pytest.mark.req("REQ-63")
def test_a_refusal_is_a_failure_on_that_head_with_its_reason() -> None:
    outcome = evidence_failure(_HEAD, "the evidence is for another commit")
    assert outcome.state is GateDecisionStateType.FAILURE and outcome.head_sha == _HEAD
    assert "another commit" in outcome.reason


@pytest.mark.req("REQ-63")
def test_evidence_for_another_repository_fails_and_the_right_one_passes_on() -> None:
    assert evidence_repository_failure(_HEAD, "o/svc", "o/svc") is None
    other = evidence_repository_failure(_HEAD, "o/svc", "o/meta")
    assert evidence_repository_failure(_HEAD, "o/svc", "x/svc") is not None
    assert other is not None and other.state is GateDecisionStateType.FAILURE


@pytest.mark.req("REQ-63")
def test_a_pass_names_the_run_of_the_evidence() -> None:
    passed = GateDecisionOutcome(
        state=GateDecisionStateType.SUCCESS, head_sha=_HEAD, reason="signed", signer="s"
    )
    named = with_evidence(passed, 12, 99, 2)
    assert named.state is GateDecisionStateType.SUCCESS
    assert "run 99.2" in named.reason and "12 tests" in named.reason


@pytest.mark.req("REQ-63")
def test_a_wave_gate_checked_without_evidence_settings_fails() -> None:
    rule = GateRule(
        label="wave-accepted",
        branch="develop",
        rung=RungType.L2,
        holders=frozenset({"h"}),
        wave=True,
    )
    outcome = wave_without_evidence(_HEAD, rule)
    assert outcome.state is GateDecisionStateType.FAILURE
    assert "wave gate" in outcome.reason and "none is configured" in outcome.reason
