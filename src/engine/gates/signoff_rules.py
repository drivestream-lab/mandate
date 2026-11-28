"""Reads a gate's signoff from a pull request snapshot. Pure: no IO, no clock.

A signoff is three things on the current head: the gate's label, an Approve whose body carries
the attestation for this head and gate, and the pull request marked ready. All three are
required, and the Approve must come from someone who holds the gate at its rung. Nothing is
assumed: a missing or unreadable part is a reason, never a pass. No timeout or default exists
here, so a gate held by a person has no signoff until that person's Approve is on the head.
"""

import yaml
from pydantic import ValidationError

from src.models.signoff_models import (
    Attestation,
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewStateType,
    SignoffAssessment,
    SignoffReading,
)


def read_attestation(body: str) -> Attestation | None:
    """The attestation in a review body, or None when it is absent or does not fit."""
    try:
        document = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    if not isinstance(document, dict) or "attestation" not in document:
        return None
    try:
        return Attestation.model_validate(document["attestation"])
    except ValidationError:
        return None


def _standing_reviews(snapshot: PullRequestSnapshot) -> list[PullReview]:
    """Each reviewer's latest review that counts: a comment does not change their standing."""
    latest: dict[str, PullReview] = {}
    for review in sorted(snapshot.reviews, key=lambda item: item.submitted_at):
        if review.state in (ReviewStateType.COMMENTED, ReviewStateType.PENDING):
            continue
        latest[review.reviewer] = review
    return list(latest.values())


def assess_signoff(snapshot: PullRequestSnapshot, rule: GateRule) -> SignoffAssessment:
    """The signoff on the current head for this gate, or the reason there is none."""
    if rule.label not in snapshot.labels:
        return _refused(f"the gate label {rule.label} is not on the pull request")
    if snapshot.is_draft:
        return _refused("the pull request is not marked ready")
    approves = [
        review
        for review in _standing_reviews(snapshot)
        if review.state is ReviewStateType.APPROVED and review.commit_id == snapshot.head_sha
    ]
    if not approves:
        return _refused(f"no Approve stands on the current head {snapshot.head_sha}")
    matching: list[tuple[PullReview, Attestation]] = []
    for review in approves:
        attestation = read_attestation(review.body)
        if (
            attestation is not None
            and attestation.head == snapshot.head_sha
            and attestation.gate == rule.label
        ):
            matching.append((review, attestation))
    if not matching:
        return _refused("no Approve on the head carries an attestation for this head and gate")
    for review, attestation in matching:
        if review.reviewer in rule.holders:
            return SignoffAssessment(
                signoff=SignoffReading(
                    signer=review.reviewer,
                    label=rule.label,
                    head_sha=snapshot.head_sha,
                    signed_at=review.submitted_at,
                    attestation=attestation,
                ),
                reason=None,
            )
    signers = ", ".join(sorted({review.reviewer for review, _ in matching}))
    return _refused(f"{signers} does not hold the gate {rule.label} at {rule.rung.value}")


def _refused(reason: str) -> SignoffAssessment:
    return SignoffAssessment(signoff=None, reason=reason)
