"""Who merges and what Mandate applies before it does. Pure: no IO, no clock.

At L0 and L1 a person signs and the merger the workflow names merges once the check passes;
Mandate neither signs nor merges. At L2 and L3 the deciding role signs and Mandate's App applies
the three signoff artifacts (the gate's label, an Approve carrying the attestation, the pull
request ready) and merges the exact commit the check passed on.
"""

import hashlib
from collections.abc import Sequence
from datetime import datetime

import yaml
from pydantic import ValidationError

from src.models.gate_models import PullRequestRef
from src.models.ledger_models import DecisionOption, DecisionRecord, EvidenceReference, RungType
from src.models.signoff_models import Attestation, GateRule, PullRequestSnapshot

MANDATE_MERGES_AT = frozenset({RungType.L2, RungType.L3})
"""The rungs where Mandate's App applies the signoff and merges."""

APPROVE_CHOICE = "approve"
REQUEST_CHANGES_CHOICE = "request_changes"
ATTESTATION_EVIDENCE = "attestation"
_DECISION_WORKFLOW = "merge-decision/1"
_DECISION_MODEL = "deciding-role"

LEFT_TO_MERGER = (
    "at this rung a person signs and the merger the workflow names merges once the check "
    "passes; Mandate does not merge"
)


def mandate_merges(rung: RungType) -> bool:
    """True only at the rungs where the deciding role signs and Mandate merges."""
    return rung in MANDATE_MERGES_AT


def attestation_body(attestation: Attestation) -> str:
    """The Approve's body: the attestation as the check reads it."""
    return yaml.safe_dump(
        {"attestation": attestation.model_dump(mode="json")},
        sort_keys=False,
        default_flow_style=False,
    )


def signoff_problem(
    snapshot: PullRequestSnapshot, rule: GateRule, attestation: Attestation
) -> str | None:
    """Why Mandate must not apply this signoff, or None when it names exactly this pull request.

    The attestation must be for the head that is there now, for this gate, repository and pull
    request, and the pull request must merge into the branch the gate decides.
    """
    if not mandate_merges(rule.rung):
        return LEFT_TO_MERGER
    if snapshot.base_ref != rule.branch:
        return f"the pull request merges into {snapshot.base_ref}, not {rule.branch}"
    if attestation.head != snapshot.head_sha:
        return "the attestation is for another head than the pull request has now"
    if attestation.gate != rule.label:
        return f"the attestation is for gate {attestation.gate}, not {rule.label}"
    if attestation.repo != snapshot.ref.repo or attestation.pull_request != snapshot.ref.number:
        return "the attestation is for another repository or pull request"
    return None


def merge_decision_role(rule: GateRule, ref: PullRequestRef) -> str:
    """The role a deciding role's merge decision is recorded under: this gate on this pull request."""
    return f"{rule.label} merge {ref.repo}#{ref.number}"


def merge_decision_record(
    rule: GateRule,
    ref: PullRequestRef,
    attestation: Attestation,
    choice: str,
    decided_at: datetime,
) -> DecisionRecord:
    """The deciding role's decision on this head, carrying the attestation Mandate's App will
    sign with if the choice is to approve. The role that decided is `rule.deciding_role`."""
    if rule.deciding_role is None:
        raise ValueError("the gate names no deciding role")
    text = attestation.model_dump_json()
    return DecisionRecord(
        actor=rule.deciding_role,
        role=merge_decision_role(rule, ref),
        rung=rule.rung,
        options_offered=(
            DecisionOption(option_id=APPROVE_CHOICE, description="Approve this head"),
            DecisionOption(
                option_id=REQUEST_CHANGES_CHOICE, description="Do not approve this head"
            ),
        ),
        choice=choice,
        reasons=(f"the deciding role decided {choice} on {attestation.head}",),
        evidence=(
            EvidenceReference(
                kind=ATTESTATION_EVIDENCE,
                reference=text,
                digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            ),
        ),
        target_version=attestation.head,
        workflow_version=_DECISION_WORKFLOW,
        model_version=_DECISION_MODEL,
        decided_at=decided_at,
    )


def decided_attestation(record: DecisionRecord | None) -> Attestation | str:
    """The attestation of the deciding role's recorded approve, or the reason there is none.

    Mandate's App carries out a decision; it never makes one, so without a recorded approve
    that carries an attestation whose digest holds there is nothing to apply.
    """
    if record is None:
        return "the ledger holds no decision of the deciding role for this head"
    if record.choice != APPROVE_CHOICE:
        return f"the deciding role's recorded decision is {record.choice}, not approve"
    held = [item for item in record.evidence if item.kind == ATTESTATION_EVIDENCE]
    if len(held) != 1:
        return "the deciding role's decision carries no single attestation"
    text = held[0].reference
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != held[0].digest:
        return "the attestation in the deciding role's decision does not match its digest"
    try:
        return Attestation.model_validate_json(text)
    except ValidationError:
        return "the attestation in the deciding role's decision is not readable"


def void_after_decision(
    decision: DecisionRecord, voids: Sequence[DecisionRecord | None]
) -> str | None:
    """Why the deciding role's decision no longer stands, or None.

    A void Mandate recorded for this gate and head after the decision ended it, even if the head
    has since come back (a force-push to the decided commit): the deciding role must decide again.
    """
    for void in voids:
        if void is not None and void.decided_at > decision.decided_at:
            return (
                "the signoff on this head was voided after the deciding role decided; "
                "the deciding role must decide again"
            )
    return None
