"""Journey: a wave passes the check only with run-signed evidence for its exact head, and Mandate
merges only where it signs.

Real wave branch on mandate-sandbox-svc with a caller workflow that runs on push, real evidence,
the signoff by mandate-challenger, the check posted by Mandate's own App. A head that moves fails
until its own evidence exists. At L0 Mandate does not merge. At L2 Mandate's App applies the
signoff on a sandbox pull request and merges with the sha pinned to the verified head.
"""

import time

import pytest

from src.business_services.gates.gate_decision_check_service import WaveEvidence
from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.business_services.release.merge_service import MergeService, MergeStateType
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.evidence_models import WaveEvidenceSpec
from src.models.ledger_models import RungType
from src.models.signoff_models import Attestation, GateDecisionStateType, GateRule
from tests.journeys.journey_support import SandboxGitHub
from tests.journeys.release_a_wave.conftest import FULL_REPO, TEST_SET, WaveBuilder
from tests.journeys.release_a_wave.support import (
    commit_parents,
    open_pull,
    pull_state,
)
from tests.journeys.sign_a_gate.conftest import SIGNER_LOGIN
from tests.journeys.sign_a_gate.support import STAMP, Services

SVC = "mandate-sandbox-svc"
META = "mandate-sandbox-meta"
GATE = "wave-accepted"
_L2 = GateRule(label=GATE, branch="develop", rung=RungType.L2, holders=frozenset({SIGNER_LOGIN}))
_L0 = GateRule(label=GATE, branch="develop", rung=RungType.L0, holders=frozenset({SIGNER_LOGIN}))


def _spec(workflow: str, digest: str) -> WaveEvidenceSpec:
    return WaveEvidenceSpec(
        repository=FULL_REPO,
        caller_workflow=workflow,
        test_set=TEST_SET,
        expected_test_set_digest=digest,
    )


@pytest.mark.req("REQ-63")
@pytest.mark.req("REQ-108")
async def test_a_wave_passes_only_with_evidence_for_the_exact_head_and_mandate_never_merges_at_l0(
    postgres: PostgresService,
    github_app: GitHubAppService,
    wave_builder: WaveBuilder,
    evidence_service: EvidenceVerificationService,
    signed_off_digest: str,
    author_token: str,
    signer_token: str,
    mandate_token: str,
    run_namespace: object,
) -> None:
    services = Services(postgres)
    wave = wave_builder.wave_branch("wave-merge")
    assert wave_builder.wait_for_run(wave.head) == "success"
    pull = open_pull(
        SVC, wave.branch, author_token, signer_token, mandate_token, "[journey] wave", True
    )
    try:
        assert pull.head_sha() == wave.head
        pull.signer_signs(GATE)
        right = WaveEvidence(evidence_service, {GATE: _spec(wave.workflow, signed_off_digest)})
        wrong = WaveEvidence(evidence_service, {GATE: _spec(wave.workflow, "0" * 64)})

        # Evidence for this head, as the caller fixed it at spec sign-off: the check passes.
        passed = await services.check.evaluate_and_post(
            github_app, pull.ref, _L2, STAMP, wave=right
        )
        assert passed.state is GateDecisionStateType.SUCCESS, passed.reason
        assert "evidence run" in passed.reason
        posted = pull.gate_decision()
        assert posted is not None and posted.state == "success"

        # The same signoff over another test set than the one fixed at sign-off: failure.
        refused = await services.check.evaluate_and_post(
            github_app, pull.ref, _L2, STAMP, wave=wrong
        )
        assert refused.state is GateDecisionStateType.FAILURE
        assert "no run-signed evidence" in refused.reason and "sign-off" in refused.reason

        # At L0 the merger the workflow names merges; Mandate checks and does not merge.
        merges = MergeService(services.check)
        at_l0 = await merges.settle(github_app, pull.ref, _L0, STAMP, wave=right)
        assert at_l0.state is MergeStateType.LEFT_TO_MERGER
        assert at_l0.check is not None and at_l0.check.state is GateDecisionStateType.FAILURE
        assert pull_state(SVC, mandate_token, pull.ref.number) == "open"

        # The head moves: the signoff and the evidence are for the old head. Signed again, the
        # new head still fails until the run for it has produced its own evidence.
        moved = wave_builder.push_file(wave.branch, "wave-merge-more.txt", "more")
        deadline = time.monotonic() + 240
        while pull.head_sha() != moved and time.monotonic() < deadline:
            time.sleep(1)
        assert pull.head_sha() == moved
        pull.signer_signs(GATE)
        early = await services.check.evaluate_and_post(github_app, pull.ref, _L2, STAMP, wave=right)
        assert early.state is GateDecisionStateType.FAILURE and early.head_sha == moved
        assert "no run-signed evidence" in early.reason, early.reason
        wave_builder.wait_for_run(moved)
        later = await services.check.evaluate_and_post(github_app, pull.ref, _L2, STAMP, wave=right)
        assert later.state is GateDecisionStateType.SUCCESS, later.reason
        assert later.head_sha == moved
        assert (await services.ledger.verify()).is_intact
    finally:
        pull.close()


@pytest.mark.req("REQ-63")
async def test_at_l2_mandates_app_applies_the_signoff_and_merges_at_the_verified_head(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_github: SandboxGitHub,
    author_token: str,
    signer_token: str,
    mandate_token: str,
) -> None:
    services = Services(postgres)
    app_login = await github_app.app_login()
    rule = GateRule(label=GATE, branch="develop", rung=RungType.L2, holders=frozenset({app_login}))
    branch = sandbox_github.create_branch(META, "mandate-merges")
    pull = open_pull(
        META,
        branch,
        author_token,
        signer_token,
        mandate_token,
        "[journey] mandate merges",
        True,
        "mandate-merges",
    )
    try:
        first = pull.head_sha()
        stale = Attestation(
            initiative="INIT-JOURNEY",
            head=first,
            gate=GATE,
            repo=META,
            pull_request=pull.ref.number,
            digests=("c" * 64,),
            artifact_paths=("journey.txt",),
        )
        moved = pull.author_pushes("mandate-merges-moved")
        merges = MergeService(services.check)

        # An attestation for a head that is not the pull request's head is not applied.
        refused = await merges.settle(github_app, pull.ref, rule, STAMP, stale)
        assert refused.state is MergeStateType.NOT_SIGNED
        assert pull_state(META, mandate_token, pull.ref.number) == "open"

        current = stale.model_copy(update={"head": moved})
        outcome = await merges.settle(github_app, pull.ref, rule, STAMP, current)
        assert outcome.state is MergeStateType.MERGED, outcome.reason
        assert outcome.check is not None and outcome.check.head_sha == moved
        assert pull_state(META, mandate_token, pull.ref.number) == "merged"
        assert moved in commit_parents(META, mandate_token, outcome.merge_commit or "")
        assert (await services.ledger.verify()).is_intact
    finally:
        pull.close()
