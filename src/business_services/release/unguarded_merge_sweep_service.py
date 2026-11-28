"""One sweep over the governed repositories: merges that had no passing check, and gate rulesets
or branch protection that are not what a decided Launchpad run left.

Merges. Every commit that landed on develop or main since the sweep's start is looked at (the
branch's own first-parent line: merge commits, squashed commits and commits pushed straight to it;
a commit a pull request brought in is reached through its merge). One that came in through a merged
pull request is judged on the head that was merged: the newest mandate/gate-decision
at or before the merge must be a success posted by Mandate's App. One pushed without a pull request
is judged on itself. A merge that fails is a policy breach: it is recorded in the ledger, escalated
to the owner, and answered with a revert pull request, which goes through the gate like any other.
On Mandate's own repositories a merge by a named emergency human is recorded as the emergency
exception with its evidence (who, which commit, when) and escalated, and is not reverted. On any
other repository there is no exception. A direct push has no pull request to revert, so it is
recorded and escalated without one.

Rulesets. The state is judged, not the actor: each ruleset and each governed branch's protection
is reduced to a digest and compared with the baseline the caller supplies. Anything that differs,
appeared or disappeared is a breach, and so is a missing or empty baseline. A ruleset change cannot
be reverted by a pull request, so the answer is the record and the escalation.

Only merge commits and squash merges can be matched to their pull request; a rebase merge lands
each commit on its own and is judged as pushes.

A finding already in the ledger from an earlier sweep is not recorded, escalated or reverted again.
A repository or branch that cannot be read is escalated, never skipped silently. Escalation today is
an error log and a returned note; no channel to the owner exists yet.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from injector import inject
from pydantic import JsonValue

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.engine.gates.unguarded_merge_rules import (
    breach_reason,
    emergency_reason,
    governance_findings,
    judge_merge,
    landings,
    protection_digest,
    ruleset_digest,
)
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, EvidenceReference, RungType
from src.models.signoff_models import GOVERNED_BRANCHES, MANDATE_ACTOR
from src.models.sweep_models import (
    BranchCommit,
    BreachKindType,
    GovernanceFinding,
    HeadStatus,
    MergeObservation,
    MergeVerdictType,
    OpenedRevert,
    PullMerge,
    RecordedFinding,
    RepoBaseline,
    SweepConfig,
    SweepEscalation,
    SweepReport,
)

POLICY_BREACH_ROLE = "policy-breach"
EMERGENCY_EXCEPTION_ROLE = "emergency-exception"
_WORKFLOW_VERSION = "unguarded-merge-sweep/1"
_RULES_VERSION = "mandate-rules"
_EVIDENCE_KIND = "sweep-finding"


class SweepGitHub(Protocol):
    """What a sweep reads from GitHub, and the one thing it writes."""

    async def list_branch_commits(
        self, repo: str, branch: str, since: datetime
    ) -> tuple[BranchCommit, ...]: ...

    async def merged_pulls_since(
        self, repo: str, branch: str, since: datetime
    ) -> tuple[PullMerge, ...]: ...

    async def list_head_statuses(self, repo: str, sha: str) -> tuple[HeadStatus, ...]: ...

    async def list_rulesets(self, repo: str) -> Mapping[int, Mapping[str, JsonValue]]: ...

    async def read_branch_protection(self, repo: str, branch: str) -> JsonValue: ...

    async def open_revert_pull(self, node_id: str) -> int: ...


class _Found:
    """What one repository's sweep gathered."""

    def __init__(self) -> None:
        self.findings: list[RecordedFinding] = []
        self.escalations: list[SweepEscalation] = []
        self.reverts: list[OpenedRevert] = []


class UnguardedMergeSweepService(BaseBusinessService):
    """Finds unguarded merges and unauthorised gate changes, records them and answers them."""

    @inject
    def __init__(self, ledger: LedgerAppendService) -> None:
        super().__init__()
        self._ledger = ledger

    async def sweep(
        self, github: SweepGitHub, config: SweepConfig, stamp: VersionStamp
    ) -> SweepReport:
        """Sweep every repository of the configuration once."""
        found = _Found()
        baselines = {item.repo: item for item in config.baselines}
        for repo in config.repos:
            await self._sweep_merges(github, config, repo, stamp, found)
            await self._sweep_governance(github, repo, baselines.get(repo), stamp, found)
        return SweepReport(
            findings=tuple(found.findings),
            escalations=tuple(found.escalations),
            reverts=tuple(found.reverts),
        )

    async def _sweep_merges(
        self,
        github: SweepGitHub,
        config: SweepConfig,
        repo: str,
        stamp: VersionStamp,
        found: _Found,
    ) -> None:
        for branch in sorted(GOVERNED_BRANCHES):
            try:
                observations = await self._observe(github, repo, branch, config.since)
            except Exception as error:  # a branch that cannot be read is for the owner to see
                self._escalate(
                    found, repo, f"{branch} merges", f"could not be read ({type(error).__name__})"
                )
                continue
            for observation in observations:
                verdict = judge_merge(
                    observation, config.mandate_login, config.own_repos, config.emergency_humans
                )
                if verdict is MergeVerdictType.GUARDED:
                    continue
                try:
                    await self._answer(github, observation, verdict, stamp, found)
                except Exception as error:
                    self._escalate(
                        found,
                        repo,
                        observation.merge_commit,
                        f"the merge could not be recorded or answered ({type(error).__name__})",
                    )

    async def _observe(
        self, github: SweepGitHub, repo: str, branch: str, since: datetime
    ) -> list[MergeObservation]:
        observations: list[MergeObservation] = []
        commits = await github.list_branch_commits(repo, branch, since)
        merged = {
            pull.merge_commit_sha: pull
            for pull in await github.merged_pulls_since(repo, branch, since)
            if pull.merge_commit_sha is not None
        }
        for commit in landings(commits):
            pull = merged.get(commit.sha)
            head = pull.head_sha if pull else commit.sha
            observations.append(
                MergeObservation(
                    repo=repo,
                    branch=branch,
                    merge_commit=commit.sha,
                    head_sha=head,
                    merged_by=pull.merged_by if pull else commit.committer,
                    merged_at=pull.merged_at if pull else _utc(commit.committed_at),
                    pull_number=pull.number if pull else None,
                    node_id=pull.node_id if pull else None,
                    statuses=await github.list_head_statuses(repo, head),
                )
            )
        return observations

    async def _answer(
        self,
        github: SweepGitHub,
        observation: MergeObservation,
        verdict: MergeVerdictType,
        stamp: VersionStamp,
        found: _Found,
    ) -> None:
        emergency = verdict is MergeVerdictType.EMERGENCY_EXCEPTION
        reason = emergency_reason(observation) if emergency else breach_reason(observation)
        kind = BreachKindType.EMERGENCY_MERGE if emergency else BreachKindType.UNGUARDED_MERGE
        recorded = await self._record(
            EMERGENCY_EXCEPTION_ROLE if emergency else POLICY_BREACH_ROLE,
            kind,
            observation.merge_commit,
            reason,
            observation.merged_by or MANDATE_ACTOR,
            stamp,
        )
        if not recorded:
            return
        found.findings.append(
            RecordedFinding(
                kind=kind, repo=observation.repo, subject=observation.merge_commit, detail=reason
            )
        )
        self._escalate(found, observation.repo, observation.merge_commit, reason)
        if emergency:
            return
        if observation.node_id is None or observation.pull_number is None:
            self._escalate(
                found,
                observation.repo,
                observation.merge_commit,
                "no revert pull request: the commit was pushed without a pull request",
            )
            return
        revert = await github.open_revert_pull(observation.node_id)
        found.reverts.append(
            OpenedRevert(
                repo=observation.repo, reverted_pull=observation.pull_number, revert_pull=revert
            )
        )

    async def _sweep_governance(
        self,
        github: SweepGitHub,
        repo: str,
        baseline: RepoBaseline | None,
        stamp: VersionStamp,
        found: _Found,
    ) -> None:
        try:
            rulesets = await github.list_rulesets(repo)
            protections = {
                branch: await github.read_branch_protection(repo, branch)
                for branch in sorted(GOVERNED_BRANCHES)
            }
        except Exception as error:  # what cannot be read cannot be shown to be unchanged
            self._escalate(found, repo, "rulesets", f"could not be read ({type(error).__name__})")
            return
        findings = governance_findings(
            repo,
            {ruleset_id: ruleset_digest(doc) for ruleset_id, doc in rulesets.items()},
            {branch: protection_digest(doc) for branch, doc in protections.items()},
            baseline,
        )
        for finding in findings:
            await self._record_governance(finding, stamp, found)

    async def _record_governance(
        self, finding: GovernanceFinding, stamp: VersionStamp, found: _Found
    ) -> None:
        subject = f"{finding.repo}: {finding.subject}"
        try:
            recorded = await self._record(
                POLICY_BREACH_ROLE,
                BreachKindType.GOVERNANCE_CHANGE,
                subject,
                f"{finding.repo}: {finding.reason}",
                MANDATE_ACTOR,
                stamp,
            )
        except Exception as error:
            self._escalate(
                found,
                finding.repo,
                finding.subject,
                f"could not be recorded ({type(error).__name__})",
            )
            return
        if recorded:
            found.findings.append(
                RecordedFinding(
                    kind=BreachKindType.GOVERNANCE_CHANGE,
                    repo=finding.repo,
                    subject=finding.subject,
                    detail=finding.reason,
                )
            )
            self._escalate(found, finding.repo, finding.subject, finding.reason)

    async def _record(
        self,
        role: str,
        kind: BreachKindType,
        target: str,
        reason: str,
        seen_by: str,
        stamp: VersionStamp,
    ) -> bool:
        """Write the finding once per role and target; False when an earlier sweep wrote it."""
        record = DecisionRecord(
            actor=MANDATE_ACTOR,
            role=role,
            rung=RungType.L0,
            options_offered=(DecisionOption(option_id=kind.value, description=reason),),
            choice=kind.value,
            reasons=(reason, f"acted by {seen_by}"),
            evidence=(
                EvidenceReference(
                    kind=_EVIDENCE_KIND,
                    reference=target,
                    digest=sha256(reason.encode("utf-8")).hexdigest(),
                ),
            ),
            target_version=target,
            workflow_version=_WORKFLOW_VERSION,
            model_version=_RULES_VERSION,
            decided_at=datetime.now(UTC),
        )
        return (
            await self._ledger.record_decision_once(record, stamp, "the finding changed")
            is not None
        )

    def _escalate(self, found: _Found, repo: str, subject: str, reason: str) -> None:
        self.logger.error("policy escalation", repo=repo, subject=subject, reason=reason)
        found.escalations.append(SweepEscalation(repo=repo, subject=subject, reason=reason))


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
