"""A non-merge decision is a holder's verdict on the head, or a holder's answer to the question."""

from datetime import UTC, datetime

import pytest

from src.engine.gates.non_merge_rules import (
    APPROVE_OPTION,
    REQUEST_CHANGES_OPTION,
    decision_from_answer,
    decision_from_review,
)
from src.models.gate_models import PullRequestRef
from src.models.paperclip_models import (
    InteractionKindType,
    InteractionStatusType,
    PaperclipQuestion,
    QuestionAnswer,
    QuestionResult,
)
from src.models.signoff_models import PullRequestSnapshot, PullReview, ReviewStateType

_HEAD = "a" * 40
_HOLDERS = frozenset({"holder[bot]"})


def _snapshot(who: str, state: ReviewStateType, commit: str = _HEAD) -> PullRequestSnapshot:
    review = PullReview(
        reviewer=who,
        state=state,
        commit_id=commit,
        body="",
        submitted_at=datetime(2026, 11, 27, tzinfo=UTC),
    )
    return PullRequestSnapshot(
        ref=PullRequestRef(repo="r", number=1),
        head_sha=_HEAD,
        labels=(),
        is_draft=True,
        reviews=(review,),
    )


def _question(status: InteractionStatusType, by: str | None, option: str) -> PaperclipQuestion:
    return PaperclipQuestion(
        id="q1",
        issue_id="i1",
        kind=InteractionKindType.ASK_USER_QUESTIONS,
        status=status,
        resolved_by_user_id=by,
        result=QuestionResult(
            answers=(QuestionAnswer(question_id="triage", option_ids=(option,)),)
        ),
    )


@pytest.mark.req("REQ-121")
def test_a_holders_verdict_on_the_head_is_the_decision() -> None:
    approve = decision_from_review(_snapshot("holder[bot]", ReviewStateType.APPROVED), _HOLDERS)
    no = decision_from_review(_snapshot("holder[bot]", ReviewStateType.CHANGES_REQUESTED), _HOLDERS)
    assert approve is not None and approve.option_id == APPROVE_OPTION
    assert no is not None and no.option_id == REQUEST_CHANGES_OPTION


@pytest.mark.req("REQ-121")
def test_a_comment_a_stale_review_or_a_non_holder_is_no_decision() -> None:
    assert (
        decision_from_review(_snapshot("holder[bot]", ReviewStateType.COMMENTED), _HOLDERS) is None
    )
    stale = _snapshot("holder[bot]", ReviewStateType.APPROVED, commit="b" * 40)
    assert decision_from_review(stale, _HOLDERS) is None
    assert decision_from_review(_snapshot("other", ReviewStateType.APPROVED), _HOLDERS) is None


@pytest.mark.req("REQ-121")
def test_an_answer_counts_only_from_a_holder_on_an_answered_question() -> None:
    answered = _question(InteractionStatusType.ANSWERED, "holder[bot]", "accept")
    read = decision_from_answer(answered, "triage", _HOLDERS)
    assert read is not None and read.option_id == "accept"
    assert (
        decision_from_answer(
            _question(InteractionStatusType.PENDING, None, "accept"), "triage", _HOLDERS
        )
        is None
    )
    assert (
        decision_from_answer(
            _question(InteractionStatusType.ANSWERED, "other", "accept"), "triage", _HOLDERS
        )
        is None
    )
