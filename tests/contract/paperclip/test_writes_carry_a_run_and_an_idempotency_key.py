"""Contract: every Paperclip write is made inside a run Mandate woke, with a kernel-derived key.

Runs against the pinned Paperclip of the run's own stack. Nothing is replaced by a fake.
"""

import uuid

import httpx
import pytest

from src.engine.kernel.idempotency_key import derive_idempotency_key
from src.infra_services.paperclip_service import PaperclipService, WriteOutsideRunError
from src.models.paperclip_models import (
    NewIssue,
    NewQuestion,
    PaperclipRun,
    QuestionOption,
    RunStatusType,
)
from tests.contract.paperclip.paperclip_stack import MandateIdentity

pytestmark = pytest.mark.req("REQ-40")


def _work_item() -> str:
    return f"work-item-{uuid.uuid4().hex[:12]}"


def _question() -> NewQuestion:
    return NewQuestion(
        question_id="choice",
        title="Which way",
        prompt="Pick one option",
        options=(QuestionOption(id="a", label="A"), QuestionOption(id="b", label="B")),
    )


async def test_an_issue_is_filed_inside_the_run_mandate_woke(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    work_item = _work_item()

    run = await paperclip.open_run(work_item, "file")
    issue = await paperclip.create_issue(run, work_item, "file", NewIssue(title="Filed in a run"))

    assert run.agent_id == mandate_identity.agent_id
    assert issue.origin_run_id == run.id
    assert issue.created_by_agent_id == mandate_identity.agent_id
    assert issue.project_id == mandate_identity.project_id
    assert issue.assignee_agent_id is None


async def test_a_repeated_write_has_one_effect(paperclip: PaperclipService) -> None:
    work_item = _work_item()
    run = await paperclip.open_run(work_item, "repeat")
    issue = await paperclip.create_issue(run, work_item, "repeat", NewIssue(title="Once"))

    again = await paperclip.create_issue(run, work_item, "repeat", NewIssue(title="Once"))
    comment = await paperclip.post_comment(run, work_item, "repeat", issue.id, "One comment")
    comment_again = await paperclip.post_comment(run, work_item, "repeat", issue.id, "One comment")
    question = await paperclip.open_question(run, work_item, "repeat", issue.id, _question())
    question_again = await paperclip.open_question(run, work_item, "repeat", issue.id, _question())
    other_step = await paperclip.create_issue(run, work_item, "another", NewIssue(title="Twice"))

    assert again.id == issue.id
    assert comment_again.id == comment.id
    assert len(await paperclip.list_comments(issue.id)) == 1
    assert question_again.id == question.id
    assert len(await paperclip.list_questions(issue.id)) == 1
    assert other_step.id != issue.id


async def test_the_key_sent_is_the_one_the_kernel_derives(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    work_item = _work_item()
    run = await paperclip.open_run(work_item, "derive")
    issue = await paperclip.create_issue(run, work_item, "derive", NewIssue(title="Keyed"))
    question = await paperclip.open_question(run, work_item, "derive", issue.id, _question())

    expected_issue_key = derive_idempotency_key(work_item, "derive:issue").value
    expected_question_key = derive_idempotency_key(work_item, "derive:question").value
    token = mandate_identity.token_file.read_text(encoding="utf-8").strip()
    async with httpx.AsyncClient(
        base_url=mandate_identity.base_url, headers={"Authorization": f"Bearer {token}"}
    ) as raw:
        replay = await raw.post(
            f"/api/companies/{mandate_identity.company_id}/issues",
            headers={"X-Paperclip-Run-Id": run.id},
            json={"title": "Keyed", "idempotencyKey": expected_issue_key},
        )

    assert question.idempotency_key == expected_question_key
    assert replay.json()["id"] == issue.id


async def test_a_write_outside_a_run_mandate_opened_is_refused_before_it_is_sent(
    paperclip: PaperclipService,
) -> None:
    work_item = _work_item()
    run = await paperclip.open_run(work_item, "real")
    foreign = PaperclipRun(id=str(uuid.uuid4()), agent_id=run.agent_id, status=RunStatusType.QUEUED)

    with pytest.raises(WriteOutsideRunError):
        await paperclip.create_issue(foreign, work_item, "real", NewIssue(title="No run"))


async def test_paperclip_itself_rejects_a_run_that_does_not_exist(
    mandate_identity: MandateIdentity,
) -> None:
    token = mandate_identity.token_file.read_text(encoding="utf-8").strip()
    async with httpx.AsyncClient(
        base_url=mandate_identity.base_url, headers={"Authorization": f"Bearer {token}"}
    ) as raw:
        response = await raw.post(
            f"/api/companies/{mandate_identity.company_id}/issues",
            headers={"X-Paperclip-Run-Id": str(uuid.uuid4())},
            json={"title": "Unknown run"},
        )

    assert response.status_code == 403
