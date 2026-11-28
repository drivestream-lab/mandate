"""Journey: a change to an upstream pull request after the holder reviewed against it makes the
downstream signoff stale.

The upstream pull request stands for the PRD and the downstream one for the spec, both real
sandbox pull requests. The link between them is passed to the check. The baseline is what the
holder attested in the Approve: the upstream head reviewed against, not what Mandate sees first.
"""

import pytest

from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.signoff_models import ArtifactLink, GateDecisionStateType
from tests.journeys.sign_a_gate.conftest import GATE_RULE, REPO, SIGNER_LOGIN, SandboxDesk
from tests.journeys.sign_a_gate.support import STAMP, Services
from tests.journeys.work_changes_after_approval.support import (
    edit_review_body,
    remove_label,
    voids_recorded,
)


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
    first_upstream_head = upstream.head_sha()
    downstream.signer_signs(upstream=[(upstream.ref, first_upstream_head)])
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
    voids = await voids_recorded(services, "spec-lgtm stale")
    assert len(voids) == 1 and voids[0].target_version == signed_head
    assert upstream_head in voids[0].choice

    # Removing the label, or approving again against the old upstream head, does not restore it.
    remove_label(author_token, downstream.ref, "spec-stale")
    downstream.review(
        signer_token,
        "APPROVE",
        downstream.attestation(upstream=[(upstream.ref, first_upstream_head)]),
    )
    same_head = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert same_head.state is GateDecisionStateType.FAILURE

    # A new downstream head, signed against the new upstream head, passes; Mandate clears the label.
    new_head = downstream.author_pushes("spec-revised-for-the-prd")
    downstream.review(
        signer_token, "APPROVE", downstream.attestation(upstream=[(upstream.ref, upstream_head)])
    )
    again = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert again.state is GateDecisionStateType.SUCCESS and again.head_sha == new_head
    assert "spec-stale" not in (await github_app.read_pull_request(downstream.ref)).labels
    assert (await services.ledger.verify()).is_intact


@pytest.mark.req("REQ-121")
async def test_an_upstream_pushed_before_the_first_check_still_makes_the_signoff_stale(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    upstream = sandbox_desk.open_pull_request("prd-pushed-before-first-check")
    downstream = sandbox_desk.open_pull_request("spec-signed-before-the-push")
    links = (ArtifactLink(upstream=upstream.ref, downstream=downstream.ref),)
    downstream.signer_signs(upstream=[(upstream.ref, upstream.head_sha())])
    upstream_head = upstream.author_pushes("prd-changed-before-any-check")

    first = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )

    assert first.state is GateDecisionStateType.FAILURE and "spec-stale" in first.reason
    voids = await voids_recorded(services, "spec-lgtm stale")
    assert len(voids) == 1 and upstream_head in voids[0].choice


@pytest.mark.req("REQ-121")
async def test_a_linked_upstream_the_holder_did_not_attest_makes_the_signoff_stale(
    postgres: PostgresService, github_app: GitHubAppService, sandbox_desk: SandboxDesk
) -> None:
    services = Services(postgres)
    upstream = sandbox_desk.open_pull_request("prd-not-attested")
    downstream = sandbox_desk.open_pull_request("spec-without-upstream-attested")
    links = (ArtifactLink(upstream=upstream.ref, downstream=downstream.ref),)
    downstream.signer_signs()

    outcome = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )

    assert outcome.state is GateDecisionStateType.FAILURE and "spec-stale" in outcome.reason


@pytest.mark.req("REQ-121")
async def test_an_approve_body_edited_after_signoff_fails_the_check_and_the_edit_is_recorded(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_desk: SandboxDesk,
    author_token: str,
) -> None:
    services = Services(postgres)
    upstream = sandbox_desk.open_pull_request("prd-for-edited-approve")
    downstream = sandbox_desk.open_pull_request("spec-with-edited-approve")
    links = (ArtifactLink(upstream=upstream.ref, downstream=downstream.ref),)
    first_head = upstream.head_sha()
    downstream.signer_signs(upstream=[(upstream.ref, first_head)])
    assert (
        await services.check.evaluate_and_post(
            github_app, downstream.ref, GATE_RULE, STAMP, links=links
        )
    ).state is GateDecisionStateType.SUCCESS

    # The upstream changes, then someone else rewrites the holder's Approve to attest the new head.
    changed_head = upstream.author_pushes("prd-moves-on")
    snapshot = await github_app.read_pull_request(downstream.ref)
    review = next(item for item in snapshot.reviews if item.reviewer == SIGNER_LOGIN)
    edit_review_body(
        author_token,
        downstream.ref,
        review.review_id,
        downstream.attestation(upstream=[(upstream.ref, changed_head)]),
    )

    edited = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert edited.state is GateDecisionStateType.FAILURE
    assert "edited after signoff" in edited.reason
    assert len(await voids_recorded(services, "spec-lgtm attestation edited")) == 1

    # Writing the original body back does not undo it.
    edit_review_body(author_token, downstream.ref, review.review_id, review.body)
    after = await services.check.evaluate_and_post(
        github_app, downstream.ref, GATE_RULE, STAMP, links=links
    )
    assert after.state is GateDecisionStateType.FAILURE
