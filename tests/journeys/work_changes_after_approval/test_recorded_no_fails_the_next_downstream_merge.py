"""Journey: a recorded no on a non-merge decision does not stop work, but fails the next merge.

A holder rejects the spec in a technical review on its pull request and Mandate records it. A
merge pull request downstream of the spec fails the check until the spec is revised and decided
again, or the holder withdraws the no. Nothing else is held while the no stands.
"""

from datetime import UTC, datetime

import uuid

import pytest

from src.engine.gates.non_merge_rules import decision_from_review, decision_role
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import GateClassType
from src.models.ledger_models import RungType
from src.models.signoff_models import DecisionLink, GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import GATE_RULE, SIGNER_LOGIN, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services, review_brief


@pytest.mark.req("REQ-121")
async def test_a_recorded_no_fails_the_next_downstream_merge_until_decided_again(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    signer_token: str,
) -> None:
    services = Services(postgres)
    spec = sandbox_desk.open_pull_request("spec-under-review")
    merge = sandbox_desk.open_pull_request("merge-downstream-of-spec")
    gate_id = uuid.uuid4()
    links = (
        DecisionLink(
            artifact=spec.ref,
            downstream=merge.ref,
            decision_role=decision_role(GateClassType.VERIFICATION, gate_id),
            holder=SIGNER_LOGIN,
        ),
    )
    merge.signer_signs()

    async def record_verdict() -> None:
        head = spec.head_sha()
        read = decision_from_review(await github_app.read_pull_request(spec.ref), GATE_RULE.holders)
        assert read is not None
        await services.non_merge.record_decision(
            review_brief(head), read, RungType.L0, datetime.now(UTC), STAMP, gate_id
        )

    async def merge_check() -> GateDecisionStateType:
        outcome = await services.check.evaluate_and_post(
            github_app, merge.ref, GATE_RULE, STAMP, decision_links=links
        )
        return outcome.state

    # No decision yet: work and the merge are not held.
    assert await merge_check() is GateDecisionStateType.SUCCESS

    # The holder says no; the merge downstream now fails, and the reason names the artifact.
    spec.signer_reviews("REQUEST_CHANGES")
    await record_verdict()
    failed = await services.check.evaluate_and_post(
        github_app, merge.ref, GATE_RULE, STAMP, decision_links=links
    )
    assert failed.state is GateDecisionStateType.FAILURE and "no recorded from" in failed.reason
    posted = merge.gate_decision()
    assert posted is not None and posted.state == "failure"

    # Revising the spec alone does not lift it: it has to be decided again.
    spec.author_pushes("spec-revised-after-no")
    assert await merge_check() is GateDecisionStateType.FAILURE

    # Decided again on the new head: the next merge passes.
    spec.signer_reviews("APPROVE")
    await record_verdict()
    assert await merge_check() is GateDecisionStateType.SUCCESS

    # A new no, then the holder withdraws it on the same head: the merge passes again.
    spec.author_pushes("spec-revised-again")
    spec.signer_reviews("REQUEST_CHANGES")
    await record_verdict()
    assert await merge_check() is GateDecisionStateType.FAILURE
    spec.signer_reviews("APPROVE")
    await record_verdict()
    assert await merge_check() is GateDecisionStateType.SUCCESS
    assert (await services.ledger.verify()).is_intact


@pytest.mark.req("REQ-121")
async def test_another_holders_approve_does_not_lift_the_no_of_the_decisions_holder(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    mandate_token: str,
) -> None:
    services = Services(postgres)
    spec = sandbox_desk.open_pull_request("spec-two-holders")
    merge = sandbox_desk.open_pull_request("merge-two-holders")
    gate_id = uuid.uuid4()
    links = (
        DecisionLink(
            artifact=spec.ref,
            downstream=merge.ref,
            decision_role=decision_role(GateClassType.VERIFICATION, gate_id),
            holder=SIGNER_LOGIN,
        ),
    )
    merge.signer_signs()

    async def record(holders: frozenset[str]) -> None:
        read = decision_from_review(await github_app.read_pull_request(spec.ref), holders)
        assert read is not None
        await services.non_merge.record_decision(
            review_brief(spec.head_sha()), read, RungType.L0, datetime.now(UTC), STAMP, gate_id
        )

    async def merge_state() -> GateDecisionStateType:
        outcome = await services.check.evaluate_and_post(
            github_app, merge.ref, GATE_RULE, STAMP, decision_links=links
        )
        return outcome.state

    spec.signer_reviews("REQUEST_CHANGES")
    await record(GATE_RULE.holders)
    assert await merge_state() is GateDecisionStateType.FAILURE

    # Another holder of the same class approves the same head and Mandate records it.
    spec.review(mandate_token, "APPROVE", "technical review")
    others = frozenset(
        review.reviewer
        for review in (await github_app.read_pull_request(spec.ref)).reviews
        if review.reviewer != SIGNER_LOGIN
    )
    assert others
    await record(others)
    assert await merge_state() is GateDecisionStateType.FAILURE

    # Only the holder's own later approve lifts it.
    spec.signer_reviews("APPROVE")
    await record(GATE_RULE.holders)
    assert await merge_state() is GateDecisionStateType.SUCCESS
