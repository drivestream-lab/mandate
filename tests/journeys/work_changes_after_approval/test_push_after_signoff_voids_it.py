"""Journey: a new commit after signoff voids it, and only the holder signing the new head restores it.

Real sandbox pull request authored by mandate-builder, signed by mandate-challenger, read and
checked by Mandate's own App. The status, the labels and the ledger are read back.
"""

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.signoff_models import GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import GATE_RULE, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services
from tests.journeys.work_changes_after_approval.support import remove_label, voids_recorded


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
    voids = await voids_recorded(services, "spec-revised")
    assert len(voids) == 1
    assert voids[0].target_version == signed_head and new_head in voids[0].reasons[0]

    # The same push checked again records nothing more.
    await services.check.evaluate_and_post(github_app, pull.ref, GATE_RULE, STAMP)
    assert len(await voids_recorded(services, "spec-revised")) == 1

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
