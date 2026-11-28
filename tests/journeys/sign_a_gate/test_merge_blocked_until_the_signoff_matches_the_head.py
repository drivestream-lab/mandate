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
from tests.journeys.sign_a_gate.conftest import GATE_RULE, SIGNER_LOGIN, SandboxDesk
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
