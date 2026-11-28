"""When a signoff stops counting, decided from plain values. Pure: no IO, no clock.

A new commit leaves the holder's signoff on an older head (revised). A change to an upstream
pull request after the signoff leaves it stale. A recorded no on a linked artifact fails the
next merge downstream of it. The ledger decides all three; a label only shows the state.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from src.engine.gates.non_merge_rules import REQUEST_CHANGES_OPTION
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import EvidenceReference
from src.models.signoff_models import (
    GateRule,
    PullRequestSnapshot,
    ReviewStateType,
    UpstreamHead,
)

GATE_LABEL_SUFFIX = "-lgtm"
UPSTREAM_EVIDENCE_KIND = "upstream-head"


class GateLabelNameError(ValueError):
    """A gate label that does not end in -lgtm has no -revised or -stale label."""


def _stem(rule: GateRule) -> str:
    if not rule.label.endswith(GATE_LABEL_SUFFIX) or rule.label == GATE_LABEL_SUFFIX:
        raise GateLabelNameError(f"{rule.label} does not end in {GATE_LABEL_SUFFIX}")
    return rule.label.removesuffix(GATE_LABEL_SUFFIX)


def revised_label(rule: GateRule) -> str:
    return f"{_stem(rule)}-revised"


def stale_label(rule: GateRule) -> str:
    return f"{_stem(rule)}-stale"


def revised_role(rule: GateRule) -> str:
    """The role Mandate records a revised void under."""
    return revised_label(rule)


def stale_role(rule: GateRule) -> str:
    """The role Mandate records a stale void under."""
    return stale_label(rule)


def pull_key(ref: PullRequestRef) -> str:
    return f"{ref.repo}#{ref.number}"


class EarlierApprove(NamedTuple):
    """A holder's Approve left on a head that is no longer the pull request's head."""

    reviewer: str
    head_sha: str


def earlier_approves(snapshot: PullRequestSnapshot, rule: GateRule) -> tuple[EarlierApprove, ...]:
    """Each holder Approve on an earlier head, newest first, dismissed or not.

    GitHub may dismiss an Approve when the head moves, so a dismissed one still shows which head
    the holder signed. Whether it was a signoff Mandate recorded is for the ledger to say.
    """
    found: list[EarlierApprove] = []
    for review in sorted(snapshot.reviews, key=lambda item: item.submitted_at, reverse=True):
        if (
            review.state in (ReviewStateType.APPROVED, ReviewStateType.DISMISSED)
            and review.commit_id != snapshot.head_sha
            and review.reviewer in rule.holders
        ):
            found.append(EarlierApprove(review.reviewer, review.commit_id))
    return tuple(found)


def revised_reason(new_head: str) -> str:
    return f"the head moved to {new_head}"


def upstream_evidence(heads: Sequence[UpstreamHead]) -> tuple[EvidenceReference, ...]:
    """The upstream heads a signoff was recorded against, as ledger evidence."""
    items: list[EvidenceReference] = []
    for head in heads:
        reference = f"{pull_key(head.upstream)}@{head.head_sha}"
        digest = hashlib.sha256(reference.encode()).hexdigest()
        items.append(
            EvidenceReference(kind=UPSTREAM_EVIDENCE_KIND, reference=reference, digest=digest)
        )
    return tuple(items)


def heads_signed_against(evidence: Sequence[EvidenceReference]) -> Mapping[str, str]:
    """Upstream pull request key to the head recorded when the signoff was written."""
    found: dict[str, str] = {}
    for item in evidence:
        if item.kind == UPSTREAM_EVIDENCE_KIND:
            key, _, head = item.reference.partition("@")
            found[key] = head
    return found


def changed_upstreams(
    signed_against: Mapping[str, str], now: Sequence[UpstreamHead]
) -> tuple[UpstreamHead, ...]:
    """Upstream pull requests whose head differs from the one recorded, or was never recorded."""
    return tuple(
        head for head in now if signed_against.get(pull_key(head.upstream)) != head.head_sha
    )


def stale_reason(changed: Sequence[UpstreamHead]) -> str:
    named = ", ".join(f"{pull_key(head.upstream)}@{head.head_sha}" for head in changed)
    return f"upstream changed to {named}"


def stale_failure_reason(label: str) -> str:
    return f"{label}: an upstream change voided this signoff; sign the new head"


def unresolved_no(choices_newest_first: Sequence[str | None]) -> bool:
    """True when the newest recorded decision on the artifact's heads is a no."""
    for choice in choices_newest_first:
        if choice is not None:
            return choice == REQUEST_CHANGES_OPTION
    return False


def heads_newest_first(snapshot: PullRequestSnapshot) -> tuple[str, ...]:
    """The artifact's current head, then every head a review was left on, newest review first."""
    ordered = [snapshot.head_sha]
    for review in sorted(snapshot.reviews, key=lambda item: item.submitted_at, reverse=True):
        if review.commit_id not in ordered:
            ordered.append(review.commit_id)
    return tuple(ordered)


def recorded_no_failure_reason(artifact: PullRequestRef) -> str:
    return (
        f"a recorded no stands on {pull_key(artifact)}; revise it and decide again, "
        "or the holder withdraws the no"
    )
