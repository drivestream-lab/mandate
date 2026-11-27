"""Contract: Mandate's identity files issues, comments, asks and reads, and nothing more."""

import uuid

import httpx
import pytest

from src.infra_services.paperclip_service import PaperclipService
from src.models.paperclip_models import NewIssue, NewQuestion, QuestionOption
from tests.contract.paperclip.paperclip_stack import MandateIdentity

pytestmark = pytest.mark.req("REQ-40")


def _raw(identity: MandateIdentity) -> httpx.AsyncClient:
    token = identity.token_file.read_text(encoding="utf-8").strip()
    return httpx.AsyncClient(
        base_url=identity.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )


async def test_mandate_can_file_comment_ask_and_read_state(
    paperclip: PaperclipService,
) -> None:
    work_item = f"work-item-{uuid.uuid4().hex[:12]}"
    run = await paperclip.open_run(work_item, "allowed")

    issue = await paperclip.create_issue(run, work_item, "allowed", NewIssue(title="Allowed"))
    comment = await paperclip.post_comment(run, work_item, "allowed", issue.id, "A comment")
    question = await paperclip.open_question(
        run,
        work_item,
        "allowed",
        issue.id,
        NewQuestion(
            question_id="choice",
            title="Which",
            prompt="Pick one",
            options=(QuestionOption(id="a", label="A"), QuestionOption(id="b", label="B")),
        ),
    )

    read_back = await paperclip.get_issue(issue.id)
    comments = await paperclip.list_comments(issue.id)
    questions = await paperclip.list_questions(issue.id)
    assert read_back.id == issue.id
    assert [c.id for c in comments] == [comment.id]
    assert [(q.id, q.status, q.created_by_agent_id) for q in questions] == [
        (question.id, "pending", run.agent_id)
    ]
    assert questions[0].resolved_by_agent_id is None


async def test_a_question_cannot_be_answered_by_an_agent(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    work_item = f"work-item-{uuid.uuid4().hex[:12]}"
    run = await paperclip.open_run(work_item, "answer")
    issue = await paperclip.create_issue(run, work_item, "answer", NewIssue(title="Ask"))
    question = await paperclip.open_question(
        run,
        work_item,
        "answer",
        issue.id,
        NewQuestion(
            question_id="choice",
            title="Which",
            prompt="Pick one",
            options=(QuestionOption(id="a", label="A"), QuestionOption(id="b", label="B")),
        ),
    )

    async with _raw(mandate_identity) as raw:
        response = await raw.post(
            f"/api/issues/{issue.id}/interactions/{question.id}/respond",
            headers={"X-Paperclip-Run-Id": run.id},
            json={"answers": [{"questionId": "choice", "optionIds": ["a"]}]},
        )

    assert response.status_code == 403
    assert (await paperclip.list_questions(issue.id))[0].status == "pending"


async def test_mandate_cannot_create_an_agent(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    run = await paperclip.open_run("work-item-agents", "denied")

    async with _raw(mandate_identity) as raw:
        response = await raw.post(
            f"/api/companies/{mandate_identity.company_id}/agents",
            headers={"X-Paperclip-Run-Id": run.id},
            json={
                "name": "Intruder",
                "role": "engineer",
                "adapterType": "process",
                "adapterConfig": {"command": "true"},
            },
        )

    assert response.status_code == 403


async def test_mandate_cannot_create_a_skill(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    run = await paperclip.open_run("work-item-skills", "denied")

    async with _raw(mandate_identity) as raw:
        response = await raw.post(
            f"/api/companies/{mandate_identity.company_id}/skills",
            headers={"X-Paperclip-Run-Id": run.id},
            json={"name": "intruder", "slug": "intruder", "markdown": "# intruder"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "skill_policy_denied"


async def test_mandate_cannot_assign_a_task(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    work_item = f"work-item-{uuid.uuid4().hex[:12]}"
    run = await paperclip.open_run(work_item, "assign")
    issue = await paperclip.create_issue(run, work_item, "assign", NewIssue(title="Unassigned"))

    async with _raw(mandate_identity) as raw:
        on_create = await raw.post(
            f"/api/companies/{mandate_identity.company_id}/issues",
            headers={"X-Paperclip-Run-Id": run.id},
            json={"title": "Assigned", "assigneeAgentId": mandate_identity.other_agent_id},
        )
        on_update = await raw.patch(
            f"/api/issues/{issue.id}",
            headers={"X-Paperclip-Run-Id": run.id},
            json={"assigneeAgentId": mandate_identity.other_agent_id},
        )

    assert on_create.status_code == 403
    assert on_update.status_code == 403
    assert (await paperclip.get_issue(issue.id)).assignee_agent_id is None


async def test_mandate_still_reads_its_question_beside_another_agents_card(
    paperclip: PaperclipService, mandate_identity: MandateIdentity
) -> None:
    work_item = f"work-item-{uuid.uuid4().hex[:12]}"
    run = await paperclip.open_run(work_item, "beside")
    issue = await paperclip.create_issue(run, work_item, "beside", NewIssue(title="Shared"))
    question = await paperclip.open_question(
        run,
        work_item,
        "beside",
        issue.id,
        NewQuestion(
            question_id="choice",
            title="Which",
            prompt="Pick one",
            options=(QuestionOption(id="a", label="A"), QuestionOption(id="b", label="B")),
        ),
    )

    other_token = mandate_identity.other_token_file.read_text(encoding="utf-8").strip()
    async with httpx.AsyncClient(
        base_url=mandate_identity.base_url,
        headers={"Authorization": f"Bearer {other_token}"},
        timeout=30,
    ) as other:
        woken = await other.post(
            f"/api/agents/{mandate_identity.other_agent_id}/wakeup",
            json={"source": "on_demand", "triggerDetail": "manual"},
        )
        card = await other.post(
            f"/api/issues/{issue.id}/interactions",
            headers={"X-Paperclip-Run-Id": woken.json()["id"]},
            json={
                "kind": "request_confirmation",
                "continuationPolicy": "none",
                "payload": {"version": 1, "prompt": "Proceed?"},
            },
        )
        raw_cards = (await other.get(f"/api/issues/{issue.id}/interactions")).json()

    assert card.status_code == 201
    assert {c["kind"] for c in raw_cards} == {"ask_user_questions", "request_confirmation"}
    assert [q.id for q in await paperclip.list_questions(issue.id)] == [question.id]
