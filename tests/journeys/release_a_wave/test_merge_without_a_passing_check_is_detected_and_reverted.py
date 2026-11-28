"""Journey: a merge into develop whose head had no passing check is caught and answered.

On mandate-sandbox-meta (no gate ruleset, only Launchpad's branch protection) the author merges a
pull request without any check, as a person's merger could. The sweep starts from a seeded
checkpoint (a second seed is refused) and walks the branch's first parents to it. With the author
named as an emergency human on a repo that is Mandate's own, a merged pull request is the recorded
exception and is not reverted; with no such human the next merge is a policy breach, recorded once,
escalated, and answered with a revert pull request. Both are reverted through the gate (signed,
checked, merged) so the sandbox content is restored.
"""

import asyncio

import pytest

from src.business_services.release.unguarded_merge_sweep_service import (
    EMERGENCY_EXCEPTION_ROLE,
    POLICY_BREACH_ROLE,
    REVERT_ROLE,
    CheckpointExistsError,
    UnguardedMergeSweepService,
)
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.ledger_models import DecisionRecord, LedgerEntryType
from src.models.signoff_models import GateDecisionStateType
from src.models.sweep_models import BreachKindType, SweepConfig
from tests.journeys.journey_support import RunNamespace, SandboxGitHub
from tests.journeys.release_a_wave.support import (
    AUTHOR_LOGIN,
    SandboxPull,
    file_exists,
    live_baseline,
    open_pull,
    pull_state,
)
from tests.journeys.sign_a_gate.conftest import GATE_RULE
from tests.journeys.sign_a_gate.support import STAMP, Services

META = "mandate-sandbox-meta"


async def _wait_until_listed(github: GitHubAppService, merge_commit: str) -> None:
    """GitHub is slow to list a new merge among the closed pull requests: wait for it."""
    for _ in range(24):
        if await github.merged_pulls_with_commits(META, "develop", frozenset({merge_commit})):
            return
        await asyncio.sleep(5)
    raise AssertionError("GitHub never listed the merged pull request")


@pytest.mark.req("REQ-122")
@pytest.mark.req("REQ-109")
@pytest.mark.req("REQ-63")
async def test_a_merge_without_a_passing_check_is_recorded_escalated_and_reverted(
    postgres: PostgresService,
    github_app: GitHubAppService,
    sandbox_github: SandboxGitHub,
    author_token: str,
    signer_token: str,
    mandate_token: str,
    run_namespace: RunNamespace,
) -> None:
    services = Services(postgres)
    sweeper = UnguardedMergeSweepService(services.ledger)
    app_login = await github_app.app_login()
    for branch in ("develop", "main"):
        seeded = await sweeper.seed_checkpoint(github_app, META, branch, STAMP)
        assert "taken as given" in seeded.reason
        with pytest.raises(CheckpointExistsError):  # only a sweep moves a checkpoint
            await sweeper.seed_checkpoint(github_app, META, branch, STAMP)
    baseline = await live_baseline(github_app, META)

    def config(humans: frozenset[str]) -> SweepConfig:
        return SweepConfig(
            repos=(META,),
            own_repos=frozenset({META}),
            emergency_humans=humans,
            mandate_login=app_login,
            baselines=(baseline,),
        )

    async def merge_without_a_check(name: str) -> tuple[SandboxPull, str]:
        file_name = f"{name}-{run_namespace.run_id}"
        branch = sandbox_github.create_branch(META, file_name)
        pull = open_pull(
            META,
            branch,
            author_token,
            signer_token,
            mandate_token,
            f"[journey] {name}",
            False,
            file_name,
        )
        merge_commit = pull.author_merges(pull.head_sha())
        await _wait_until_listed(github_app, merge_commit)
        return pull, merge_commit

    async def revert_through_the_gate(revert_number: int, file_name: str) -> None:
        revert = SandboxPull(META, revert_number, "", author_token, signer_token, mandate_token)
        try:
            assert pull_state(META, mandate_token, revert_number) == "open"
            signed_head = revert.signer_signs(GATE_RULE.label)
            outcome = await services.check.evaluate_and_post(
                github_app, revert.ref, GATE_RULE, STAMP
            )
            assert outcome.state is GateDecisionStateType.SUCCESS, outcome.reason
            await github_app.merge_pull(revert.ref, signed_head)
            assert pull_state(META, mandate_token, revert_number) == "merged"
            assert not file_exists(META, mandate_token, f"{file_name}.txt", "develop")
        finally:
            revert.close()

    # A named emergency human on Mandate's own repo, merging a pull request: the recorded
    # exception, escalated, not reverted.
    _, first_commit = await merge_without_a_check("emergency")
    exception = await sweeper.sweep(github_app, config(frozenset({AUTHOR_LOGIN})), STAMP)
    seen = [f for f in exception.findings if f.subject == first_commit]
    assert [f.kind for f in seen] == [BreachKindType.EMERGENCY_MERGE]
    assert AUTHOR_LOGIN in seen[0].detail and first_commit in seen[0].detail
    assert any(e.subject == first_commit for e in exception.escalations)
    assert not exception.reverts
    assert len(exception.limits) == 1
    assert await _recorded(services, EMERGENCY_EXCEPTION_ROLE, first_commit) == 1
    # Not reverted by the sweep; the journey restores the sandbox through the gate itself.
    node = (await github_app.merged_pulls_with_commits(META, "develop", frozenset({first_commit})))[
        0
    ]
    await revert_through_the_gate(
        await github_app.open_revert_pull(node.node_id), f"emergency-{run_namespace.run_id}"
    )

    # With nobody named, the next merge without a check is a breach: recorded, escalated and
    # reverted by the sweep.
    second, second_commit = await merge_without_a_check("unguarded")
    report = await sweeper.sweep(github_app, config(frozenset()), STAMP)
    breach = [f for f in report.findings if f.subject == second_commit]
    assert [f.kind for f in breach] == [BreachKindType.UNGUARDED_MERGE]
    assert any(e.subject == second_commit for e in report.escalations)
    reverts = [x for x in report.reverts if x.reverted_pull == second.ref.number]
    assert len(reverts) == 1
    assert await _recorded(services, POLICY_BREACH_ROLE, second_commit) == 1
    assert await _recorded(services, REVERT_ROLE, second_commit) == 1
    # The revert of the first merge, merged through the gate, is not a finding.
    assert not [f for f in report.findings if f.subject not in {second_commit}]

    # The sweep moved its checkpoint: a second sweep finds nothing and opens nothing.
    again = await sweeper.sweep(github_app, config(frozenset()), STAMP)
    assert again.findings == () and again.reverts == ()

    # The sweep's revert goes through the gate like any other pull request.
    await revert_through_the_gate(reverts[0].revert_pull, f"unguarded-{run_namespace.run_id}")
    after = await sweeper.sweep(github_app, config(frozenset()), STAMP)
    assert after.findings == ()
    assert (await services.ledger.verify()).is_intact


async def _recorded(services: Services, role: str, target: str) -> int:
    async with services.postgres.get_session() as session:
        entries = await services.repository.read_all(session)
    return sum(
        1
        for entry in entries
        if entry.entry_type == LedgerEntryType.DECISION
        and (record := DecisionRecord.model_validate(entry.payload)).role == role
        and record.target_version == target
    )
