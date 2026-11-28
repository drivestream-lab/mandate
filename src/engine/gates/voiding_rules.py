"""When a signoff stops counting, decided from plain values. Pure: no IO, no clock.

A new commit leaves the holder's signoff on an older head (revised). A change to an upstream
pull request after the holder reviewed against it leaves the signoff stale. A recorded no on a
linked artifact fails the next merge downstream of it. The ledger decides all three; a label only
shows the state.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from src.engine.gates.non_merge_rules import REQUEST_CHANGES_OPTION
from src.engine.gates.signoff_rules import read_attestation
from src.models.gate_models import PullRequestRef
from src.models.ledger_models import EvidenceReference
from src.models.signoff_models import (
    Attestation,
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewStateType,
    UpstreamHead,
)

GATE_LABEL_SUFFIX = "-lgtm"
WAVE_GATE_LABEL = "wave-accepted"
WAVE_STEM = "wave"
UPSTREAM_EVIDENCE_KIND = "upstream-head"
VOIDED_REVIEW_EVIDENCE_KIND = "voided-review"
ATTESTATION_EVIDENCE_KIND = "attestation-body"


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
    """The role Mandate records a revised void under: keyed on the gate's own label, never on
    the display label, so renaming a display label hides no earlier void."""
    return f"{rule.label} revised"


def stale_role(rule: GateRule) -> str:
    """The role Mandate records a stale void under, keyed on the gate's own label."""
    return f"{rule.label} stale"


def pull_key(ref: PullRequestRef) -> str:
    return f"{ref.repo}#{ref.number}"


class EarlierApprove(NamedTuple):
    """A holder's Approve left on a head that is no longer the pull request's head."""

    reviewer: str
    head_sha: str
    review_id: int


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
            found.append(EarlierApprove(review.reviewer, review.commit_id, review.review_id))
    return tuple(found)


def approves_on_head(snapshot: PullRequestSnapshot, head_sha: str) -> tuple[int, ...]:
    """The ids of every Approve left on this head, by any reviewer, dismissed or not."""
    return tuple(
        sorted(
            review.review_id
            for review in snapshot.reviews
            if review.commit_id == head_sha
            and review.state in (ReviewStateType.APPROVED, ReviewStateType.DISMISSED)
        )
    )


def stale_approves_on_head(
    snapshot: PullRequestSnapshot, upstream_now: Sequence[UpstreamHead]
) -> tuple[int, ...]:
    """The Approves on the head a stale void names: those whose attested upstream heads differ
    from the current ones, or whose body is not a readable attestation. An Approve already given
    against the current upstream heads is left alone."""
    ids: list[int] = []
    for review in snapshot.reviews:
        if review.commit_id != snapshot.head_sha or review.state not in (
            ReviewStateType.APPROVED,
            ReviewStateType.DISMISSED,
        ):
            continue
        attestation = read_attestation(review.body)
        if isinstance(attestation, str) or changed_upstreams(
            attested_upstream_heads(attestation), upstream_now
        ):
            ids.append(review.review_id)
    return tuple(sorted(ids))


def edited_approves(snapshot: PullRequestSnapshot, rule: GateRule) -> tuple[PullReview, ...]:
    """The holders' Approves on the current head whose body was ever edited."""
    return tuple(
        review
        for review in snapshot.reviews
        if review.edited
        and review.commit_id == snapshot.head_sha
        and review.state is ReviewStateType.APPROVED
        and review.reviewer in rule.holders
    )


def body_digest(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def attestation_role(rule: GateRule) -> str:
    """The role the pinned digest of a signer's Approve body is recorded under."""
    return f"{rule.label} attestation"


def attestation_edited_role(rule: GateRule) -> str:
    """The role Mandate records an edit of a signed Approve body under."""
    return f"{rule.label} attestation edited"


def attestation_key(head_sha: str, review_id: int) -> str:
    return f"{head_sha}#{review_id}"


def attestation_evidence(review_id: int, digest: str) -> tuple[EvidenceReference, ...]:
    return (
        EvidenceReference(
            kind=ATTESTATION_EVIDENCE_KIND, reference=f"review {review_id}", digest=digest
        ),
    )


def pinned_digest(evidence: Sequence[EvidenceReference]) -> str | None:
    for item in evidence:
        if item.kind == ATTESTATION_EVIDENCE_KIND:
            return item.digest
    return None


EDITED_FAILURE_REASON = "the Approve was edited; the holder must approve again"
NOT_PINNED_REASON = "no attestation is pinned for this signoff; only the event check pins one"


def review_evidence(review_ids: Sequence[int]) -> tuple[EvidenceReference, ...]:
    """The Approve reviews a void covers, as ledger evidence."""
    items: list[EvidenceReference] = []
    for review_id in review_ids:
        reference = f"review {review_id}"
        digest = hashlib.sha256(reference.encode()).hexdigest()
        items.append(
            EvidenceReference(kind=VOIDED_REVIEW_EVIDENCE_KIND, reference=reference, digest=digest)
        )
    return tuple(items)


def voided_review_ids(evidence: Sequence[EvidenceReference]) -> frozenset[int]:
    """The review ids a void's evidence names."""
    return frozenset(
        int(item.reference.removeprefix("review "))
        for item in evidence
        if item.kind == VOIDED_REVIEW_EVIDENCE_KIND
    )


def revised_cause(review_ids: Sequence[int], new_head: str) -> str:
    """Why a signoff is void; the Approves it voided and the head that voided them."""
    return f"voided: reviews {', '.join(str(i) for i in review_ids)} do not cover {new_head}"


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


def stale_cause(changed: Sequence[UpstreamHead], review_id: int) -> str:
    named = ", ".join(f"{pull_key(head.upstream)}@{head.head_sha}" for head in changed)
    return f"voided: review {review_id} was not given against {named}"


def stale_failure_reason(label: str) -> str:
    return f"{label}: an upstream change voided this signoff; sign it again against the new head"


def void_failure_reason(label: str) -> str:
    return f"{label}: the Approve on this head was voided; the holder must approve it again"


def signoff_is_voided(review_id: int, voided: frozenset[int]) -> bool:
    """True when the Approve behind the signoff is one a void on this head names."""
    return review_id in voided


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
