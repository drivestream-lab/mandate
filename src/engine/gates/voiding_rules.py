"""When a signoff stops counting, decided from plain values. Pure: no IO, no clock.

A new commit leaves the holder's signoff on an older head (revised). A change to an upstream
pull request after the holder reviewed against it leaves the signoff stale. A recorded no on a
linked artifact fails the next merge downstream of it. The ledger decides all three; a label only
shows the state.
"""

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple

from src.engine.gates.non_merge_rules import REQUEST_CHANGES_OPTION
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import EvidenceReference
from src.models.signoff_models import (
    Attestation,
    GateRule,
    PullRequestSnapshot,
    ReviewStateType,
    UpstreamHead,
)

GATE_LABEL_SUFFIX = "-lgtm"
WAVE_GATE_LABEL = "wave-accepted"
WAVE_STEM = "wave"
UPSTREAM_EVIDENCE_KIND = "upstream-head"


def _stem(label: str) -> str:
    if label == WAVE_GATE_LABEL:
        return WAVE_STEM
    return label.removesuffix(GATE_LABEL_SUFFIX) if label != GATE_LABEL_SUFFIX else label


def revised_label(rule: GateRule) -> str:
    """The rule's own -revised label, else spec-lgtm gives spec-revised and wave-accepted gives
    wave-revised; any other label is followed by -revised."""
    return rule.revised_label or f"{_stem(rule.label)}-revised"


def stale_label(rule: GateRule) -> str:
    """The rule's own -stale label, else spec-lgtm gives spec-stale and wave-accepted gives
    wave-stale; any other label is followed by -stale."""
    return rule.stale_label or f"{_stem(rule.label)}-stale"


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
    submitted_at: datetime


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
            found.append(EarlierApprove(review.reviewer, review.commit_id, review.submitted_at))
    return tuple(found)


def revised_cause(earlier: EarlierApprove, new_head: str) -> str:
    """Why a signoff is void; each signoff voided by each new head is its own cause."""
    return (
        f"voided: the signoff of {earlier.submitted_at.isoformat()} " f"does not cover {new_head}"
    )


def upstream_evidence(heads: Sequence[UpstreamHead]) -> tuple[EvidenceReference, ...]:
    """Upstream heads as ledger evidence on a stale void."""
    items: list[EvidenceReference] = []
    for head in heads:
        reference = f"{pull_key(head.upstream)}@{head.head_sha}"
        digest = hashlib.sha256(reference.encode()).hexdigest()
        items.append(
            EvidenceReference(kind=UPSTREAM_EVIDENCE_KIND, reference=reference, digest=digest)
        )
    return tuple(items)


def attested_upstream_heads(attestation: Attestation) -> Mapping[str, str]:
    """Upstream pull request key to the head the holder attested to reviewing against."""
    return {f"{item.repo}#{item.pull_request}": item.head for item in attestation.upstream}


def changed_upstreams(
    attested: Mapping[str, str], now: Sequence[UpstreamHead]
) -> tuple[UpstreamHead, ...]:
    """Upstream pull requests whose head differs from the attested one, or is not attested."""
    return tuple(head for head in now if attested.get(pull_key(head.upstream)) != head.head_sha)


def stale_cause(changed: Sequence[UpstreamHead], signed_at: datetime) -> str:
    named = ", ".join(f"{pull_key(head.upstream)}@{head.head_sha}" for head in changed)
    return f"voided: the signoff of {signed_at.isoformat()} was not given against {named}"


def stale_failure_reason(label: str) -> str:
    return f"{label}: an upstream change voided this signoff; sign it again against the new head"


def void_failure_reason(label: str) -> str:
    return f"{label}: this head carries a void; the holder must sign it again"


def signoff_follows_void(signed_at: datetime, void_at: datetime | None) -> bool:
    """True when there is no void for this head, or the holder signed strictly after it."""
    return void_at is None or signed_at > void_at


def latest_time(times: Sequence[datetime | None]) -> datetime | None:
    found = [moment for moment in times if moment is not None]
    return max(found) if found else None


def unresolved_no(choices_newest_first: Sequence[str | None]) -> bool:
    """True when the holder's newest recorded decision on the artifact's heads is a no."""
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


def recorded_no_failure_reason(artifact: PullRequestRef, holder: str) -> str:
    return (
        f"a no recorded from {holder} stands on {pull_key(artifact)}; revise it and decide again, "
        "or the holder withdraws the no"
    )
