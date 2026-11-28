"""Journey: a gate ruleset or branch protection that is not what the baseline allows is a breach.

Real rulesets and branch protection are read from mandate-sandbox-svc with Mandate's test App. A
baseline built from what is there finds nothing. The baseline is then changed the way a changed
ruleset would differ from it (another digest, a ruleset it does not list, one it lists that is gone,
a branch protection that differs) and each difference is recorded once and escalated; a missing or
empty baseline is itself a breach. Nothing here changes a real ruleset: only the repository owner
does, so the difference is made on the baseline side. A ruleset change cannot be reverted by a pull
request, so the answer is the record and the escalation.
"""

from datetime import UTC, datetime

import pytest

from src.business_services.release.unguarded_merge_sweep_service import (
    POLICY_BREACH_ROLE,
    UnguardedMergeSweepService,
)
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.postgres_service import PostgresService
from src.models.ledger_models import DecisionRecord, LedgerEntryType
from src.models.sweep_models import (
    BreachKindType,
    ProtectionBaseline,
    RepoBaseline,
    RulesetBaseline,
    SweepConfig,
)
from tests.journeys.release_a_wave.support import live_baseline
from tests.journeys.sign_a_gate.support import STAMP, Services

SVC = "mandate-sandbox-svc"
_OTHER_DIGEST = "e" * 64


def _config(app_login: str, *baselines: RepoBaseline) -> SweepConfig:
    return SweepConfig(
        repos=(SVC,),
        mandate_login=app_login,
        since=datetime.now(UTC),
        baselines=baselines,
    )


@pytest.mark.req("REQ-122")
async def test_a_ruleset_or_protection_that_differs_from_the_baseline_is_recorded_and_escalated(
    postgres: PostgresService, github_app: GitHubAppService
) -> None:
    services = Services(postgres)
    sweeper = UnguardedMergeSweepService(services.ledger)
    login = await github_app.app_login()
    live = await live_baseline(github_app, SVC)
    assert live.rulesets, "the sandbox repo has its gate ruleset"

    # What a decided run left, as it stands: nothing to record.
    clean = await sweeper.sweep(github_app, _config(login, live), STAMP)
    assert clean.findings == () and clean.escalations == ()

    first = live.rulesets[0]
    cases = {
        "differs from the baseline": live.model_copy(
            update={
                "rulesets": (
                    RulesetBaseline(ruleset_id=first.ruleset_id, digest=_OTHER_DIGEST),
                    *live.rulesets[1:],
                )
            }
        ),
        "is not in the baseline": live.model_copy(
            update={"rulesets": live.rulesets[1:], "protections": live.protections}
        ),
        "is in the baseline but no longer exists": live.model_copy(
            update={
                "rulesets": (*live.rulesets, RulesetBaseline(ruleset_id=1, digest=_OTHER_DIGEST))
            }
        ),
        "protection of develop differs": live.model_copy(
            update={
                "protections": (
                    ProtectionBaseline(branch="develop", digest=_OTHER_DIGEST),
                    *[p for p in live.protections if p.branch != "develop"],
                )
            }
        ),
    }
    for fragment, baseline in cases.items():
        report = await sweeper.sweep(github_app, _config(login, baseline), STAMP)
        assert [fragment in f.detail for f in report.findings] == [True], (fragment, report)
        assert report.findings[0].kind is BreachKindType.GOVERNANCE_CHANGE
        assert [e.reason for e in report.escalations] == [report.findings[0].detail]
        assert report.reverts == ()
        # The same difference swept again is already on the record.
        repeat = await sweeper.sweep(github_app, _config(login, baseline), STAMP)
        assert repeat.findings == () and repeat.escalations == ()

    # No baseline is a breach: there is nothing to compare against. One that lists nothing is the
    # same breach, already on the record by then.
    missing = await sweeper.sweep(github_app, _config(login), STAMP)
    assert [f.subject for f in missing.findings] == ["baseline"]
    assert len(missing.escalations) == 1
    empty = await sweeper.sweep(github_app, _config(login, RepoBaseline(repo=SVC)), STAMP)
    assert empty.findings == ()

    async with postgres.get_session() as session:
        entries = await services.repository.read_all(session)
    roles = [
        DecisionRecord.model_validate(e.payload).role
        for e in entries
        if e.entry_type == LedgerEntryType.DECISION
    ]
    assert roles and set(roles) == {POLICY_BREACH_ROLE}
    assert len(roles) == len(cases) + 1
    assert (await services.ledger.verify()).is_intact
