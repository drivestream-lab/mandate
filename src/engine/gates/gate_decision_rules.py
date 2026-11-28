"""What mandate/gate-decision posts, decided from plain values. Pure: no IO, no clock.

The check reads GitHub and the ledger; this module only judges what it read. Every fault maps
to failure, a success that no longer holds on the second read maps to failure, and a commit
that heads another open pull request into a governed branch cannot be signed once for both.
"""

from collections.abc import Sequence

from src.models.gate_models import PullRequestRef
from src.models.signoff_models import (
    GOVERNED_BRANCHES,
    GateDecisionOutcome,
    GateDecisionStateType,
    GateRule,
    OpenPull,
    SignoffAssessment,
    SignoffReading,
)

PAGE_SIZE = 100


def next_page(page: int, batch_size: int) -> int | None:
    """The next page to ask GitHub for, or None once a short page shows the list has ended."""
    return page + 1 if batch_size >= PAGE_SIZE else None


def sharing_pulls(
    candidates: Sequence[OpenPull], head_sha: str, own: PullRequestRef
) -> tuple[OpenPull, ...]:
    """Other open pull requests into a governed branch whose head is exactly this commit."""
    return tuple(
        pull
        for pull in candidates
        if pull.head_sha == head_sha and pull.ref != own and pull.base_ref in GOVERNED_BRANCHES
    )


MORE_THAN_ONE_GATE_LABEL = "more than one gate label"


def gate_labels_present(
    labels: Sequence[str], base_ref: str, rules: Sequence[GateRule]
) -> list[str]:
    """The gate labels of this branch that are on the pull request."""
    return sorted(
        {rule.label for rule in rules if rule.branch == base_ref and rule.label in labels}
    )


def more_than_one_gate_label(
    labels: Sequence[str], base_ref: str, rules: Sequence[GateRule]
) -> bool:
    """True when the pull request carries the labels of two gates of its branch."""
    return len(gate_labels_present(labels, base_ref, rules)) > 1


def ambiguous_gate(head_sha: str) -> GateDecisionOutcome:
    """Failure for a pull request whose gate cannot be told: it names more than one."""
    return failure(head_sha, f"{MORE_THAN_ONE_GATE_LABEL} is on the pull request")


def choose_rule(pull: OpenPull, rules: Sequence[GateRule]) -> GateRule | GateDecisionOutcome:
    """The gate a pull request names by its label, or the failure to post.

    None of the branch's gate labels, or more than one, is a failure: a label never picks a
    gate when it is not the only one.
    """
    present = gate_labels_present(pull.labels, pull.base_ref, rules)
    if len(present) > 1:
        return ambiguous_gate(pull.head_sha)
    for rule in rules:
        if rule.branch == pull.base_ref and rule.label in present:
            return rule
    return no_gate_label(pull.head_sha, pull, rules)


def no_gate_label(head_sha: str, pull: OpenPull, rules: Sequence[GateRule]) -> GateDecisionOutcome:
    """Failure for a pull request carrying none of the gate labels of its branch."""
    labels = sorted(rule.label for rule in rules if rule.branch == pull.base_ref)
    named = ", ".join(labels) if labels else f"no gate is configured for {pull.base_ref}"
    return failure(head_sha, f"none of the gate labels ({named}) is on the pull request")


def not_recorded_for_recheck(head_sha: str, rule: GateRule) -> GateDecisionOutcome:
    """Failure when the re-check finds no recorded decision for this gate on this head."""
    return failure(
        head_sha,
        f"the ledger holds no decision for gate {rule.label} on this head; "
        "only the event check records one",
    )


def failure(head_sha: str, reason: str) -> GateDecisionOutcome:
    return GateDecisionOutcome(
        state=GateDecisionStateType.FAILURE, head_sha=head_sha, reason=reason, signer=None
    )


def failure_after_fault(head_sha: str, error_name: str) -> GateDecisionOutcome:
    """Any fault once the head is known: fail on that head, naming the kind of fault."""
    return failure(head_sha, f"the signoff could not be read or recorded ({error_name})")


def refusal_for(
    head_sha: str, assessment: SignoffAssessment, sharing: Sequence[OpenPull]
) -> GateDecisionOutcome | None:
    """Failure when the signoff is missing or the commit is shared; None when both are clear."""
    if assessment.signoff is None:
        return failure(head_sha, assessment.reason or "no signoff")
    if sharing:
        numbers = ", ".join(f"#{pull.ref.number}" for pull in sharing)
        return failure(
            head_sha,
            f"this commit is also the head of {numbers}, so one signoff cannot cover both",
        )
    return None


def outcome_after_recording(
    head_sha: str, rule: GateRule, signoff: SignoffReading, recorded: bool
) -> GateDecisionOutcome:
    """Success only when the signer's decision is in the ledger."""
    if not recorded:
        return failure(head_sha, "the decision is not in the ledger")
    return GateDecisionOutcome(
        state=GateDecisionStateType.SUCCESS,
        head_sha=head_sha,
        reason=f"{rule.label} signed by {signoff.signer} on this head and recorded",
        signer=signoff.signer,
    )


def withdrawal_for(
    posted: GateDecisionOutcome, second_head: str, second: SignoffAssessment
) -> GateDecisionOutcome | None:
    """Failure replacing a success that the second read no longer supports; None when it holds."""
    signoff = second.signoff
    if signoff is not None and second_head == posted.head_sha and signoff.signer == posted.signer:
        return None
    reason = second.reason or "the head moved or the signer changed"
    return failure(posted.head_sha, f"the signoff no longer holds: {reason}")


def withdrawal_after_fault(posted: GateDecisionOutcome, error_name: str) -> GateDecisionOutcome:
    """Failure replacing a success when the second read itself failed."""
    return failure(
        posted.head_sha, f"the signoff no longer holds: it could not be read again ({error_name})"
    )
