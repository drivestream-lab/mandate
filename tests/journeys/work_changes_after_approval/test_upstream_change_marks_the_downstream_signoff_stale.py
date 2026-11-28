"""Journey: a change to an upstream pull request after a downstream signoff makes it stale.

The upstream pull request stands for the PRD and the downstream one for the spec, both real
sandbox pull requests. The link between them is passed to the check. The downstream head does
not move, yet its signoff stops counting, and only a signoff on a new head restores it.
"""

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.signoff_models import ArtifactLink, GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import GATE_RULE, REPO, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services
from tests.journeys.work_changes_after_approval.support import remove_label, voids_recorded


@pytest.mark.req("REQ-121")
async def test_an_upstream_change_applies_stale_and_the_downstream_is_signed_again_on_its_new_head(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    author_token: str,
    signer_token: str,
) -> None:
    services = Services(postgres)
    upstream = sandbox_desk.open_pull_request("prd-upstream")
    downstream = sandbox_desk.open_pull_request("spec-downstream")
    links = (ArtifactLink(upstream=upstream.ref, downstream=downstream.ref),)
    downstream.signer_signs()
    signed_head = downstream.head_sha()
    signed = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert signed.state is GateDecisionStateType.SUCCESS

    upstream_head = upstream.author_pushes("prd-changed")

    # The re-check finds it without any event on the downstream pull request.
    report = await services.check.recheck_open_gates(
        github_app, (REPO,), (GATE_RULE,), STAMP, links=links
    )
    mine = [o for o in report.outcomes if o.head_sha == signed_head]
    assert mine and all(o.state is GateDecisionStateType.FAILURE for o in mine)
    assert downstream.head_sha() == signed_head
    posted = downstream.gate_decision()
    assert posted is not None and posted.state == "failure"
    assert "spec-stale" in (await github_app.read_pull_request(downstream.ref)).labels
    voids = await voids_recorded(services, "spec-stale")
    assert len(voids) == 1 and voids[0].target_version == signed_head
    assert upstream_head in voids[0].reasons[0]

    # Removing the label, or the holder approving the same head again, does not restore it.
    remove_label(author_token, downstream.ref, "spec-stale")
    downstream.review(signer_token, "APPROVE", downstream.attestation())
    same_head = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert same_head.state is GateDecisionStateType.FAILURE
    assert len(await voids_recorded(services, "spec-stale")) == 1

    # A new downstream head, signed by the holder, passes and Mandate clears the label.
    new_head = downstream.author_pushes("spec-revised-for-the-prd")
    downstream.review(signer_token, "APPROVE", downstream.attestation())
    again = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert again.state is GateDecisionStateType.SUCCESS and again.head_sha == new_head
    assert "spec-stale" not in (await github_app.read_pull_request(downstream.ref)).labels
    assert (await services.ledger.verify()).is_intact
