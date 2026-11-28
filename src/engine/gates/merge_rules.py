"""Who merges and what Mandate applies before it does. Pure: no IO, no clock.

At L0 and L1 a person signs and the merger the workflow names merges once the check passes;
Mandate neither signs nor merges. At L2 and L3 the deciding role signs and Mandate's App applies
the three signoff artifacts (the gate's label, an Approve carrying the attestation, the pull
request ready) and merges the exact commit the check passed on.
"""

import yaml

from src.models.ledger_models import RungType
from src.models.signoff_models import Attestation, GateRule, PullRequestSnapshot

MANDATE_MERGES_AT = frozenset({RungType.L2, RungType.L3})
"""The rungs where Mandate's App applies the signoff and merges."""

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
