"""Journey: a merge into develop whose head had no passing check is caught and answered.

On mandate-sandbox-meta (no gate ruleset, only Launchpad's branch protection) the author merges a
pull request without any check, as a person's merger could. One sweep over the merge window finds
it. With the author named as an emergency human on a repo that is Mandate's own, the merge is the
recorded exception and is not reverted; with no such human it is a policy breach, recorded once,
escalated, and answered with a revert pull request, which is signed and merged through the gate so
the sandbox content is restored.
"""

import asyncio
import pytest

from src.business_services.release.unguarded_merge_sweep_service import (
    EMERGENCY_EXCEPTION_ROLE,
    POLICY_BREACH_ROLE,
    REVERT_ROLE,
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
    file_name = f"unguarded-{run_namespace.run_id}"
    sweeper = UnguardedMergeSweepService(services.ledger)
    app_login = await github_app.app_login()
    before = await sweeper.record_checkpoint(github_app, META, "develop", STAMP)
    await sweeper.record_checkpoint(github_app, META, "main", STAMP)
    branch = sandbox_github.create_branch(META, file_name)
    pull = open_pull(
        META,
        branch,
        author_token,
        signer_token,
        mandate_token,
        "[journey] unguarded",
        False,
        file_name,
    )
    merge_commit = pull.author_merges(pull.head_sha())
    baseline = await live_baseline(github_app, META)

    def config(humans: frozenset[str]) -> SweepConfig:
        return SweepConfig(
            repos=(META,),
            own_repos=frozenset({META}),
            emergency_humans=humans,
            mandate_login=app_login,
            baselines=(baseline,),
        )

    await _wait_until_listed(github_app, merge_commit)

    # A named emergency human on Mandate's own repo, merging a pull request: the recorded
    # exception, escalated, not reverted.
    exception = await sweeper.sweep(github_app, config(frozenset({AUTHOR_LOGIN})), STAMP)
    seen = [f for f in exception.findings if f.subject == merge_commit]
    assert [f.kind for f in seen] == [BreachKindType.EMERGENCY_MERGE]
    assert AUTHOR_LOGIN in seen[0].detail and merge_commit in seen[0].detail
    assert any(e.subject == merge_commit for e in exception.escalations)
    assert not exception.reverts
    assert len(exception.limits) == 1
    assert await _recorded(services, EMERGENCY_EXCEPTION_ROLE, merge_commit) == 1
    assert pull_state(META, mandate_token, pull.ref.number) == "merged"

    # With nobody named, the same merge is a breach: recorded, escalated and reverted. (The
    # checkpoint is put back before the merge, as if the earlier sweep had not run.)
    await sweeper.record_checkpoint(github_app, META, "develop", STAMP, before)
    report = await sweeper.sweep(github_app, config(frozenset()), STAMP)
    breach = [f for f in report.findings if f.subject == merge_commit]
    assert [f.kind for f in breach] == [BreachKindType.UNGUARDED_MERGE]
    assert any(e.subject == merge_commit for e in report.escalations)
    reverts = [x for x in report.reverts if x.reverted_pull == pull.ref.number]
    assert len(reverts) == 1
    assert await _recorded(services, POLICY_BREACH_ROLE, merge_commit) == 1
    assert await _recorded(services, REVERT_ROLE, merge_commit) == 1

    # Swept again over the same landings: already recorded, and its revert is on record, so
    # nothing is recorded, escalated or reverted a second time.
    await sweeper.record_checkpoint(github_app, META, "develop", STAMP, before)
    again = await sweeper.sweep(github_app, config(frozenset()), STAMP)
    assert not [f for f in again.findings if f.subject == merge_commit]
    assert not [x for x in again.reverts if x.reverted_pull == pull.ref.number]

    # The revert goes through the gate like any other pull request, then restores the content.
    revert = SandboxPull(
        META, reverts[0].revert_pull, "", author_token, signer_token, mandate_token
    )
    try:
        assert pull_state(META, mandate_token, revert.ref.number) == "open"
        signed_head = revert.signer_signs(GATE_RULE.label)
        outcome = await services.check.evaluate_and_post(github_app, revert.ref, GATE_RULE, STAMP)
        assert outcome.state is GateDecisionStateType.SUCCESS, outcome.reason
        reverted = await github_app.merge_pull(revert.ref, signed_head)
        assert pull_state(META, mandate_token, revert.ref.number) == "merged"
        assert not file_exists(META, mandate_token, f"{file_name}.txt", "develop")
        # The revert's merge passed the check, so a sweep over it finds nothing to record.
        after = await sweeper.sweep(github_app, config(frozenset()), STAMP)
        assert not [f for f in after.findings if f.subject == reverted]
    finally:
        revert.close()
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
