"""Reads a gate's signoff from a pull request snapshot. Pure: no IO, no clock.

A signoff is three things on the current head: the gate's label, an Approve whose body carries
the full attestation for this head, gate, repository and pull request, and the pull request marked ready. All three are
required, and the Approve must come from someone who holds the gate at its rung. Nothing is
assumed: a missing or unreadable part is a reason, never a pass. No timeout or default exists
here, so a gate held by a person has no signoff until that person's Approve is on the head.
"""

import hashlib

import yaml
from pydantic import ValidationError

from src.models.ledger_models import RungType
from src.models.signoff_models import (
    Attestation,
    GateRule,
    PullRequestSnapshot,
    PullReview,
    ReviewerKindType,
    ReviewStateType,
    SignoffAssessment,
    SignoffReading,
)


def read_attestation(body: str) -> Attestation | str:
    """The attestation in a review body, or the reason it is not one (names the field)."""
    try:
        document = yaml.safe_load(body)
    except yaml.YAMLError:
        return "the Approve body is not readable as an attestation"
    if not isinstance(document, dict) or "attestation" not in document:
        return "the Approve carries no attestation"
    try:
        return Attestation.model_validate(document["attestation"])
    except ValidationError as error:
        fields = sorted({".".join(str(part) for part in item["loc"]) or "attestation"
                         for item in error.errors()})  # fmt: skip
        return "the attestation is missing or has a bad field: " + ", ".join(fields)


def _standing_reviews(snapshot: PullRequestSnapshot) -> list[PullReview]:
    """Each reviewer's latest review that counts: a comment does not change their standing."""
    latest: dict[str, PullReview] = {}
    for review in sorted(snapshot.reviews, key=lambda item: item.submitted_at):
        if review.state in (ReviewStateType.COMMENTED, ReviewStateType.PENDING):
            continue
        latest[review.reviewer] = review
    return list(latest.values())


def assess_signoff(
    snapshot: PullRequestSnapshot, rule: GateRule, excluded: frozenset[int] = frozenset()
) -> SignoffAssessment:
    """The signoff on the current head for this gate, or the reason there is none.

    Whoever applied the label or marked the pull request ready does not matter; the decision is
    the holder's attested Approve on this head, for this gate, repository and pull request.
    """
    if snapshot.base_ref != rule.branch:
        return _refused(
            f"the pull request merges into {snapshot.base_ref}, not {rule.branch}, "
            f"which gate {rule.label} decides"
        )
    if rule.label not in snapshot.labels:
        return _refused(f"the gate label {rule.label} is not on the pull request")
    if snapshot.is_draft:
        return _refused("the pull request is not marked ready")
    approves = [
        review
        for review in _standing_reviews(snapshot)
        if review.review_id not in excluded
        and review.state is ReviewStateType.APPROVED
        and review.commit_id == snapshot.head_sha
    ]
    if not approves:
        return _refused(f"no Approve stands on the current head {snapshot.head_sha}")
    problems: list[str] = []
    matching: list[tuple[PullReview, Attestation]] = []
    for review in approves:
        attestation = read_attestation(review.body)
        if isinstance(attestation, str):
            problems.append(attestation)
        elif (
            attestation.head == snapshot.head_sha
            and attestation.gate == rule.label
            and attestation.repo == snapshot.ref.repo
            and attestation.pull_request == snapshot.ref.number
        ):
            matching.append((review, attestation))
        else:
            problems.append("the attestation names another head, gate, repository or pull request")
    if not matching:
        return _refused(problems[0])
    refusals: list[str] = []
    for review, attestation in matching:
        if review.reviewer not in rule.holders:
            refusals.append(
                f"{review.reviewer} does not hold the gate {rule.label} at {rule.rung.value}"
            )
        elif rule.rung is RungType.L0 and review.reviewer_kind is not ReviewerKindType.USER:
            refusals.append(
                f"{review.reviewer} is a {review.reviewer_kind.value} account; "
                f"an L0 gate is decided by a person"
            )
        else:
            return SignoffAssessment(
                signoff=SignoffReading(
                    signer=review.reviewer,
                    label=rule.label,
                    head_sha=snapshot.head_sha,
                    review_id=review.review_id,
                    body_digest=hashlib.sha256(review.body.encode()).hexdigest(),
                    signed_at=review.submitted_at,
                    attestation=attestation,
                ),
                reason=None,
            )
    return _refused("; ".join(refusals))


def _refused(reason: str) -> SignoffAssessment:
    return SignoffAssessment(signoff=None, reason=reason)
