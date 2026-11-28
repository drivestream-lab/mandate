"""Reads a non-merge decision from where it was made. Pure: no IO, no clock.

A decision on a pull request is a holder's review on the current head: Approve or request
changes. A decision on a Paperclip question is the option a holder answered. Anything else
(a comment, a stale review, someone who does not hold the decision) is no decision yet. None of
this blocks work: absence of a decision simply means nothing is recorded.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.models.gate_models import GateClassType
from src.models.paperclip_models import InteractionStatusType, PaperclipQuestion
from src.models.signoff_models import PullRequestSnapshot, ReviewStateType

APPROVE_OPTION = "approve"
REQUEST_CHANGES_OPTION = "request_changes"


class ReadDecision(BaseModel):
    """A holder's decision as read: who, which option and when (None when the source has no time)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    holder: str
    option_id: str
    decided_at: datetime | None


def decision_from_review(
    snapshot: PullRequestSnapshot, holders: frozenset[str]
) -> ReadDecision | None:
    """The latest verdict review by a holder on the current head, or None."""
    verdicts = {
        ReviewStateType.APPROVED: APPROVE_OPTION,
        ReviewStateType.CHANGES_REQUESTED: REQUEST_CHANGES_OPTION,
    }
    latest: ReadDecision | None = None
    for review in sorted(snapshot.reviews, key=lambda item: item.submitted_at):
        if (
            review.reviewer in holders
            and review.commit_id == snapshot.head_sha
            and review.state in verdicts
        ):
            latest = ReadDecision(
                holder=review.reviewer,
                option_id=verdicts[review.state],
                decided_at=review.submitted_at,
            )
    return latest


def decision_from_answer(
    question: PaperclipQuestion, question_id: str, holders: frozenset[str]
) -> ReadDecision | None:
    """The option a holder answered, or None while the question is open or unanswered."""
    resolver = question.resolved_by_user_id
    if question.status is not InteractionStatusType.ANSWERED or resolver not in holders:
        return None
    if question.result is None:
        return None
    for answer in question.result.answers:
        if answer.question_id == question_id and len(answer.option_ids) == 1:
            return ReadDecision(holder=resolver, option_id=answer.option_ids[0], decided_at=None)
    return None


def decision_role(gate_class: GateClassType, gate_id: UUID | None) -> str:
    """The role a decision is recorded under: its class, and its own gate when it has one.

    Two decisions of the same class on different gates are different roles, so one holder's
    word on one never stands in for another.
    """
    base = f"{gate_class.value} decision"
    return base if gate_id is None else f"{base} {gate_id}"
