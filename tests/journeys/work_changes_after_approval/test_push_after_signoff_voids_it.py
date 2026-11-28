"""Journey: a new commit after signoff voids it, and only the holder signing the new head restores it.

Real sandbox pull request authored by mandate-builder, signed by mandate-challenger, read and
checked by Mandate's own App. The status, the labels and the ledger are read back.
"""

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.ledger_models import RungType
from src.models.signoff_models import GateDecisionStateType, GateRule
from tests.journeys.sign_a_gate.conftest import GATE_LABEL, GATE_RULE, SIGNER_LOGIN, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services
from tests.journeys.work_changes_after_approval.support import (
    WAVE_RULE,
    remove_label,
    voids_recorded,
)


@pytest.mark.req("REQ-42")
@pytest.mark.req("REQ-63")
async def test_a_push_after_signoff_applies_revised_posts_failure_and_records_the_void(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    author_token: str,
    signer_token: str,
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("push-after-signoff")
    pull.signer_signs()
    signed_head = pull.head_sha()
    signed = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert signed.state is GateDecisionStateType.SUCCESS

    new_head = pull.author_pushes("after-signoff")

    voided = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert (
        voided.state is GateDecisionStateType.FAILURE and voided.head_sha == new_head
    ), voided.reason
    posted = pull.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert "spec-revised" in (await github_app.read_pull_request(pull.ref)).labels, voided.reason
    voids = await voids_recorded(services, "spec-lgtm revised")
    assert len(voids) == 1
    assert voids[0].target_version == signed_head and new_head in voids[0].choice

    # The same push checked again records nothing more.
    await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert len(await voids_recorded(services, "spec-lgtm revised")) == 1

    # Anyone may remove the label; it decides nothing, so the check still fails.
    remove_label(author_token, pull.ref, "spec-revised")
    still = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert still.state is GateDecisionStateType.FAILURE

    # Only the holder's Approve on the new head restores it; Mandate clears the labels itself.
    pull.add_label(author_token, "spec-revised")
    pull.review(signer_token, "APPROVE", pull.attestation())
    again = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert again.state is GateDecisionStateType.SUCCESS and again.head_sha == new_head
    assert "spec-revised" not in (await github_app.read_pull_request(pull.ref)).labels
    assert (await services.ledger.verify()).is_intact


@pytest.mark.req("REQ-42")
async def test_a_signed_wave_gate_passes_and_a_push_voids_it_under_the_wave_labels(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("wave-push-after-signoff")
    pull.signer_signs("wave-accepted")
    signed = await services.check.evaluate_and_post(github_app, pull.ref, WAVE_RULE, STAMP)
    assert signed.state is GateDecisionStateType.SUCCESS

    new_head = pull.author_pushes("after-wave-signoff")

    voided = await services.check.evaluate_and_post(github_app, pull.ref, WAVE_RULE, STAMP)
    assert voided.state is GateDecisionStateType.FAILURE and voided.head_sha == new_head
    assert "wave-revised" in (await github_app.read_pull_request(pull.ref)).labels
    assert len(await voids_recorded(services, "wave-accepted revised")) == 1


@pytest.mark.req("REQ-42")
async def test_a_head_that_returns_to_a_signed_commit_needs_the_holder_to_sign_again(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    signer_token: str,
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("returns-to-signed-head")
    pull.signer_signs()
    signed_head = pull.head_sha()
    assert (
        await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    ).state is GateDecisionStateType.SUCCESS
    pull.author_pushes("detour")
    voided = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert voided.state is GateDecisionStateType.FAILURE
    assert len(await voids_recorded(services, "spec-lgtm revised")) == 1

    # The branch goes back to the very commit that was signed: the void still stands.
    pull.force_push_to(signed_head)
    back = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert back.state is GateDecisionStateType.FAILURE and back.head_sha == signed_head

    # Only a signoff given after the void restores it.
    pull.review(signer_token, "APPROVE", pull.attestation())
    again = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert again.state is GateDecisionStateType.SUCCESS and again.head_sha == signed_head


@pytest.mark.req("REQ-42")
async def test_the_old_approve_on_a_returned_head_is_named_by_the_void_and_does_not_count(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    signer_token: str,
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("old-approve-on-returned-head")
    pull.signer_signs()
    signed_head = pull.head_sha()
    old_approves = [
        review.review_id
        for review in (await github_app.read_pull_request(pull.ref)).reviews
        if review.commit_id == signed_head
    ]
    assert old_approves
    assert (
        await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    ).state is GateDecisionStateType.SUCCESS
    pull.author_pushes("detour-for-old-approve")
    await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)

    # The void names the Approve it covers, by review id.
    voids = await voids_recorded(services, "spec-lgtm revised")
    assert len(voids) == 1
    named = {item.reference for item in voids[0].evidence}
    assert {f"review {review_id}" for review_id in old_approves} <= named

    # Back on the signed commit the old Approve, standing or dismissed, does not restore it.
    pull.force_push_to(signed_head)
    back = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert back.state is GateDecisionStateType.FAILURE

    # A new Approve, a review no void names, does.
    pull.review(signer_token, "APPROVE", pull.attestation())
    again = await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert again.state is GateDecisionStateType.SUCCESS


@pytest.mark.req("REQ-42")
async def test_a_second_holders_earlier_approve_does_not_revive_a_returned_head_but_a_new_one_does(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    pull = sandbox_desk.open_pull_request("two-holders-returned-head")
    pull.signer_signs()
    pull.mandate_approves()
    signed_head = pull.head_sha()
    second = {
        review.reviewer
        for review in (await github_app.read_pull_request(pull.ref)).reviews
        if review.reviewer != SIGNER_LOGIN
    }
    assert len(second) == 1
    rule = GateRule(
        label=GATE_LABEL,
        branch="develop",
        rung=RungType.L2,
        holders=frozenset({SIGNER_LOGIN, *second}),
    )
    assert (
        await services.check.evaluate_and_post(github_app, pull.ref, rule, STAMP)
    ).state is GateDecisionStateType.SUCCESS
    pull.author_pushes("detour-two-holders")
    await services.check.evaluate_and_post(github_app, pull.ref, rule, STAMP)

    # Both holders' Approves on the voided head are named, so neither revives it.
    voids = await voids_recorded(services, "spec-lgtm revised")
    assert len(voids) == 1 and len(voids[0].evidence) == 2
    pull.force_push_to(signed_head)
    back = await services.check.evaluate_and_post(github_app, pull.ref, rule, STAMP)
    assert back.state is GateDecisionStateType.FAILURE

    # The second holder approving again, after the void, restores it.
    pull.mandate_approves()
    again = await services.check.evaluate_and_post(github_app, pull.ref, rule, STAMP)
    assert again.state is GateDecisionStateType.SUCCESS and again.signer in second
