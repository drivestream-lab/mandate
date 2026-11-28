"""Journey: decisions that are not merges are sealed, recorded with their holder, and never block.

One decision is asked as a review on a pull request, one as a Paperclip question. The deciding
role's call is sealed in the ledger before either is posted. A merge gate on another pull
request still passes while the decision is open and after the holder says no.
"""

import uuid
from datetime import UTC, datetime

import pytest

from src.engine.gates.non_merge_rules import REQUEST_CHANGES_OPTION, decision_from_review
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.paperclip_service import PaperclipService
from src.infra_services.postgres_service import PostgresService
from src.models.ledger_models import DecisionRecord, LedgerEntryType, RungType
from src.models.paperclip_models import InteractionStatusType, NewIssue
from src.models.signoff_models import GateDecisionStateType
from tests.journeys.journey_support import StackAddresses
from tests.journeys.sign_a_gate.conftest import GATE_RULE, SIGNER_LOGIN, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, ScriptedRole, Services, review_brief
from tests.journeys.test_agents.conftest import AgentDesk

__all__ = ["StackAddresses"]


@pytest.mark.req("REQ-121")
async def test_review_decision_is_sealed_first_recorded_with_its_holder_and_blocks_nothing(
    postgres: PostgresService,
    github_app: GitHubAppService,
    desk: AgentDesk,
    sandbox_desk: SandboxDesk,
) -> None:
    services = Services(postgres)
    reviewed = sandbox_desk.open_pull_request("technical-review")
    merge_gate = sandbox_desk.open_pull_request("merge-gate-beside-review")
    merge_gate.signer_signs()
    brief = review_brief(reviewed.head_sha())

    opened = await services.non_merge.ask_on_pull_request(
        uuid.uuid4(), brief, reviewed.ref, ScriptedRole(desk), github_app, STAMP
    )

    # The call was sealed in the ledger, and the review request is on the pull request.
    assert await services.entry_types() == [LedgerEntryType.SEALED_CALL]
    assert opened.sealed.sealed_entry_hash
    # Work is not waiting on it: an unrelated merge gate passes while the question is open.
    open_check = await services.check.evaluate_and_post(
        github_app, merge_gate.ref, GATE_RULE, STAMP
    )
    assert open_check.state is GateDecisionStateType.SUCCESS

    # The holder says no on the pull request; Mandate records it with the holder.
    reviewed.signer_reviews("REQUEST_CHANGES")
    snapshot = await github_app.read_pull_request(reviewed.ref)
    read = decision_from_review(snapshot, GATE_RULE.holders)
    assert read is not None and read.option_id == REQUEST_CHANGES_OPTION
    entry = await services.non_merge.record_decision(
        brief, read, RungType.L0, datetime.now(UTC), STAMP
    )
    assert entry is not None
    record = DecisionRecord.model_validate(entry.payload)
    assert record.actor == SIGNER_LOGIN and record.choice == REQUEST_CHANGES_OPTION
    assert (
        await services.non_merge.record_decision(brief, read, RungType.L0, datetime.now(UTC), STAMP)
        is None
    )

    # A recorded no does not stop the merge gate beside it.
    after = await services.check.evaluate_and_post(github_app, merge_gate.ref, GATE_RULE, STAMP)
    assert after.state is GateDecisionStateType.SUCCESS
    assert (await services.ledger.verify()).is_intact


@pytest.mark.req("REQ-121")
async def test_paperclip_question_is_sealed_first_and_left_open_without_blocking(
    postgres: PostgresService,
    paperclip: PaperclipService,
    desk: AgentDesk,
    sandbox_desk: SandboxDesk,
) -> None:
    services = Services(postgres)
    work_item = uuid.uuid4()
    run = await paperclip.open_run(str(work_item), "triage-issue")
    issue = await paperclip.create_issue(
        run, str(work_item), "triage-issue", NewIssue(title="Triage: new repo request")
    )
    brief = review_brief("d" * 40)

    opened, question = await services.non_merge.ask_in_paperclip(
        work_item, brief, issue.id, "triage", ScriptedRole(desk), paperclip, STAMP
    )

    assert await services.entry_types() == [LedgerEntryType.SEALED_CALL]
    assert opened.sealed.sealed_entry_hash
    assert question.status is InteractionStatusType.PENDING
    open_questions = await paperclip.list_questions(issue.id)
    assert [q.id for q in open_questions] == [question.id]
