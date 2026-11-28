"""Journey: mandate/gate-decision fails until the holder's signoff matches the current head.

Real sandbox pull request authored by mandate-builder, signed by mandate-challenger, read and
checked by Mandate's own App. The status is read back from GitHub.
"""

import asyncio

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.ledger_models import DecisionRecord, LedgerEntryType
from src.models.signoff_models import GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import (
    DESIGN_GATE_RULE,
    GATE_RULE,
    REPO,
    SIGNER_LOGIN,
    SandboxDesk,
)
from tests.journeys.sign_a_gate.support import STAMP, Services


@pytest.mark.req("REQ-63")
@pytest.mark.req("REQ-40")
@pytest.mark.req("REQ-43")
async def test_check_fails_until_signed_passes_when_signed_and_fails_after_a_push(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("merge-gate")

    # Nobody has signed: failure, however long it waits.
    first = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert first.state is GateDecisionStateType.FAILURE
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert await services.entry_types() == []

    # The holder signs: label, Approve with attestation, ready.
    pull.signer_signs()
    signed_head = pull.head_sha()
    second = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert second.state is GateDecisionStateType.SUCCESS and second.signer == SIGNER_LOGIN
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "success"
    async with postgres.get_session() as session:
        entries = await services.repository.read_all(session)
    decisions = [e for e in entries if e.entry_type == LedgerEntryType.DECISION]
    assert len(decisions) == 1
    record = DecisionRecord.model_validate(decisions[0].payload)
    assert record.actor == SIGNER_LOGIN and record.target_version == signed_head

    # A second check on the same head writes no second decision.
    await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert (await services.entry_types()).count(LedgerEntryType.DECISION) == 1

    # The author pushes: the signoff is on the old head, so the new head fails.
    new_head = pull.author_pushes("after-signoff")
    assert new_head != signed_head
    third = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert third.state is GateDecisionStateType.FAILURE and third.head_sha == new_head
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert (await services.ledger.verify()).is_intact


@pytest.mark.req("REQ-63")
async def test_a_signed_pull_request_retargeted_to_another_branch_fails_the_check(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("retargeted")
    pull.signer_signs()
    signed = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert signed.state is GateDecisionStateType.SUCCESS

    pull.retarget("main")
    retargeted = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)

    assert retargeted.state is GateDecisionStateType.FAILURE
    assert "merges into main" in retargeted.reason
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"


@pytest.mark.req("REQ-63")
async def test_a_second_open_pull_request_on_the_same_head_fails_the_check(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("shared-head")
    pull.signer_signs()
    other = pull.open_second_pull_on_same_head("twin")

    outcome = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)

    assert outcome.state is GateDecisionStateType.FAILURE
    assert f"#{other}" in outcome.reason


@pytest.mark.req("REQ-55")
async def test_two_checks_racing_on_one_signoff_write_one_decision(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("racing-checks")
    pull.signer_signs()

    outcomes = await asyncio.gather(
        *(
            services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
            for _ in range(4)
        )
    )

    assert all(o.state is GateDecisionStateType.SUCCESS for o in outcomes)
    assert (await services.entry_types()).count(LedgerEntryType.DECISION) == 1


@pytest.mark.req("REQ-63")
async def test_a_stacked_pull_request_does_not_block_the_signed_parent(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("stack-parent")
    pull.signer_signs()
    stacked = pull.open_stacked_pull_request("stack-child")

    outcome = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)

    assert stacked > 0
    assert outcome.state is GateDecisionStateType.SUCCESS


@pytest.mark.req("REQ-63")
async def test_recheck_fails_a_signed_pull_request_retargeted_without_a_new_evaluation(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("recheck-retarget")
    pull.signer_signs()
    signed = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert signed.state is GateDecisionStateType.SUCCESS
    pull.retarget("main")
    stale = pull.gate_decision()
    assert stale is not None and stale.state == "success"  # GitHub still shows the old answer

    report = await services.check.recheck_open_gates(github_app, (REPO,), (GATE_RULE,), STAMP)

    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert [o for o in report.outcomes if o.head_sha == signed.head_sha][0].state is (
        GateDecisionStateType.FAILURE
    )
    assert not [e for e in report.escalations if e.number == pull.ref.number]


@pytest.mark.req("REQ-63")
async def test_a_second_gate_label_fails_the_event_check_and_the_recheck(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    rules = (GATE_RULE, DESIGN_GATE_RULE)
    pull = sandbox_desk.open_pull_request("two-gate-labels")
    pull.signer_signs()
    signed = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP, rules)
    assert signed.state is GateDecisionStateType.SUCCESS

    pull.author_adds_label("design-lgtm")

    event = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP, rules)
    assert event.state is GateDecisionStateType.FAILURE
    assert "more than one gate label" in event.reason
    # The re-check starts from the standing success and downgrades it the same way.
    report = await services.check.recheck_open_gates(github_app, (REPO,), rules, STAMP)
    mine = [o for o in report.outcomes if o.head_sha == signed.head_sha]
    assert mine and all(o.state is GateDecisionStateType.FAILURE for o in mine)
    assert "more than one gate label" in mine[0].reason
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"


@pytest.mark.req("REQ-63")
async def test_the_recheck_never_passes_a_signoff_the_event_check_did_not_record(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("recheck-cannot-choose")
    pull.signer_signs()

    report = await services.check.recheck_open_gates(github_app, (REPO,), (GATE_RULE,), STAMP)

    mine = [o for o in report.outcomes if o.head_sha == pull.head_sha()]
    assert mine and mine[0].state is GateDecisionStateType.FAILURE
    assert "no decision" in mine[0].reason
    assert await services.entry_types() == []
