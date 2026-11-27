"""Scripted agents on Paperclip's process adapter hand back results Mandate can check."""

import pytest

from src.infra_services.paperclip_service import PaperclipService
from src.models.role_output_models import CoderResult, DecidingRoleCall, read_role_output
from tests.journeys.test_agents.conftest import AgentDesk

_BRIEF = {"options": ["ship", "hold"], "evidence": ["ci-run-1", "review-2"]}


async def _agent_comments(paperclip: PaperclipService, issue_id: str, agent_id: str) -> list[str]:
    comments = await paperclip.list_comments(issue_id)
    return [comment.body for comment in comments if comment.author_agent_id == agent_id]


@pytest.mark.req("REQ-118")
async def test_deciding_role_returns_option_reasons_and_evidence(
    desk: AgentDesk, paperclip: PaperclipService
) -> None:
    agent_id = desk.hire("Deciding role", "deciding_role.py")
    issue_id = desk.assign(agent_id, "Decide", _BRIEF)

    run = desk.first_finished_run(agent_id, issue_id)
    posted = await _agent_comments(paperclip, issue_id, agent_id)

    assert run["status"] == "succeeded"
    call = read_role_output(DecidingRoleCall, posted[0])
    assert call is not None
    assert call.option == "ship"
    assert call.reasons
    assert call.evidence_cited == ("ci-run-1", "review-2")
    assert read_role_output(DecidingRoleCall, str(run["resultJson"]["stdout"])) == call  # type: ignore[index]


@pytest.mark.req("REQ-118")
async def test_call_that_fails_its_schema_counts_as_missing(
    desk: AgentDesk, paperclip: PaperclipService
) -> None:
    agent_id = desk.hire("Deciding role without evidence", "deciding_role.py")
    issue_id = desk.assign(agent_id, "Decide", {**_BRIEF, "fault": "omit_evidence"})

    run = desk.first_finished_run(agent_id, issue_id)
    posted = await _agent_comments(paperclip, issue_id, agent_id)

    assert run["status"] == "failed"
    assert posted == []
    assert read_role_output(DecidingRoleCall, posted[0] if posted else None) is None


@pytest.mark.req("REQ-118")
async def test_scripted_coder_result_fits_the_shared_model(
    desk: AgentDesk, paperclip: PaperclipService
) -> None:
    agent_id = desk.hire("Coder", "sandbox_coder.py")
    issue_id = desk.assign(agent_id, "Code", {"task": "add a line", "branch": "journey/x"})

    desk.first_finished_run(agent_id, issue_id)
    posted = await _agent_comments(paperclip, issue_id, agent_id)

    result = read_role_output(CoderResult, posted[0])
    assert result is not None
    assert result.branch == "journey/x"
