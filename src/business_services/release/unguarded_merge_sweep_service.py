"""One sweep over the governed repositories: landings that were not a merge guarded by a passing
check, and gate rulesets or branch protection that are not what a decided Launchpad run left.

Landings. Each of develop and main is walked from its current tip back through first parents
to the tip the previous sweep recorded in the ledger (the checkpoint, written by Mandate); the
first sweep has none and goes back as far as `max_depth` landings; once there is one, GitHub's compare bounds the walk: identical judges nothing, ahead walks at most ahead_by first parents to the checkpoint, and behind or diverged (a rewrite) is recorded and escalated at once and the landings above the merge base are judged all the same. A comparison that fails or is not understood (an orphan force-push has no shared history) is recorded as a rewrite, and the tip is still walked back `max_depth` landings and judged; the checkpoint stays. Commit dates are never used.
A landing that is a merged pull request's merge commit is judged on the head that was merged: the
newest mandate/gate-decision at or before GitHub's merge time must be a success posted by
Mandate's App. A landing that is not (a push, or a rebase merge) is a breach whatever statuses it
has. A branch whose line no longer leads to the checkpoint was rewritten: a breach too. A breach
is recorded in the ledger, escalated to the owner, and answered with a revert pull request, which
goes through the gate like any other; it is handled only once that revert pull request is on
record, so a revert that failed to open is opened by the next sweep. On Mandate's own repositories
a merged pull request merged by a named emergency human is recorded as the emergency exception with
its evidence (who, which commit, when), escalated, and not reverted; a push is never an exception.
The checkpoint moves to the tip only when every landing was answered.

Rulesets. The state is judged, not the actor: each ruleset (all pages) and each governed branch's
protection is reduced to a digest and compared with the baseline the caller supplies. A
difference, an added or removed ruleset, an unreadable answer and a missing or empty baseline are
findings. A ruleset change cannot be reverted by a pull request, so the answer is the record and
the escalation. Bypass actors are not shown to Mandate's App, so they are outside the digest and
the report states that limit.

A finding already in the ledger is not recorded or escalated again. A repository or branch that
cannot be read is escalated, never skipped silently. Escalation today is an error log and a
returned note; no channel to the owner exists yet.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from injector import inject
from pydantic import JsonValue

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.exceptions.app_exceptions import BaseAppException
from src.engine.gates.unguarded_merge_rules import (
    BYPASS_LIMIT,
    breach_reason,
    checkpoint_reached,
    emergency_reason,
    governance_findings,
    judge_merge,
    protection_digest,
    plan_walk,
    revert_due,
    seed_allowed,
    ruleset_digest,
    walk_complete,
)
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, EvidenceReference, RungType
from src.models.signoff_models import GOVERNED_BRANCHES, MANDATE_ACTOR
from src.models.sweep_models import (
    BranchCommit,
    BreachKindType,
    CompareResult,
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
CHECKPOINT_ROLE = "sweep-checkpoint"
SEED_ROLE = "sweep-seed"
REVERT_ROLE = "revert-opened"
_WORKFLOW_VERSION = "unguarded-merge-sweep/1"
_RULES_VERSION = "mandate-rules"
_EVIDENCE_KIND = "sweep-finding"


class SweepGitHub(Protocol):
    """What a sweep reads from GitHub, and the one thing it writes."""

    async def read_branch_tip(self, repo: str, branch: str) -> str: ...

    async def read_commit(self, repo: str, sha: str) -> BranchCommit: ...

    async def compare(self, repo: str, base: str, head: str) -> CompareResult: ...

    async def merged_pulls_with_commits(
        self, repo: str, branch: str, shas: frozenset[str]
    ) -> tuple[PullMerge, ...]: ...

    async def list_head_statuses(self, repo: str, sha: str) -> tuple[HeadStatus, ...]: ...

    async def list_rulesets(self, repo: str) -> Mapping[int, Mapping[str, JsonValue]]: ...

    async def read_branch_protection(self, repo: str, branch: str) -> JsonValue: ...

    async def open_revert_pull(self, node_id: str) -> int: ...


class CheckpointExistsError(BaseAppException):
    """A checkpoint cannot be seeded where one exists: only a sweep moves it."""

    def __init__(self, repo: str, branch: str) -> None:
        super().__init__(
            code="SWEEP_CHECKPOINT_EXISTS",
            message=f"{repo} {branch} already has a checkpoint; only a sweep moves it",
            status_code=409,
        )


class _Found:
    """What one sweep gathered."""

    def __init__(self) -> None:
        self.findings: list[RecordedFinding] = []
        self.escalations: list[SweepEscalation] = []
        self.reverts: list[OpenedRevert] = []
        self.limits: list[str] = []


class UnguardedMergeSweepService(BaseBusinessService):
    """Finds unguarded landings and unauthorised gate changes, records them and answers them."""

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
            for branch in sorted(GOVERNED_BRANCHES):
                await self._sweep_branch(github, config, repo, branch, stamp, found)
            await self._sweep_governance(github, repo, baselines.get(repo), stamp, found)
        return SweepReport(
            findings=tuple(found.findings),
            escalations=tuple(found.escalations),
            reverts=tuple(found.reverts),
            limits=tuple(found.limits),
        )

    async def seed_checkpoint(
        self, github: SweepGitHub, repo: str, branch: str, stamp: VersionStamp
    ) -> SweepEscalation:
        """Start judging from the branch's tip as it is now: everything before it is taken as
        given. Allowed only where no checkpoint exists, recorded under Mandate's actor and
        escalated to the owner, since it means "start judging here". Afterwards only a sweep that
        answered every landing moves the checkpoint."""
        existing = await self._ledger.latest_choice(
            MANDATE_ACTOR, CHECKPOINT_ROLE, _checkpoint_target(repo, branch)
        )
        if not seed_allowed(existing):
            raise CheckpointExistsError(repo, branch)
        tip = await github.read_branch_tip(repo, branch)
        reason = f"{repo} {branch} is judged from {tip}; everything before it is taken as given"
        await self._write(SEED_ROLE, f"{repo}/{branch}@{tip}", "seeded", reason, stamp)
        await self._write_checkpoint(repo, branch, tip, stamp)
        found = _Found()
        self._escalate(found, repo, f"{branch} checkpoint seeded", reason)
        return found.escalations[0]

    async def _sweep_branch(
        self,
        github: SweepGitHub,
        config: SweepConfig,
        repo: str,
        branch: str,
        stamp: VersionStamp,
        found: _Found,
    ) -> None:
        subject = f"{branch} landings"
        try:
            tip = await github.read_branch_tip(repo, branch)
            checkpoint = await self._ledger.latest_choice(
                MANDATE_ACTOR, CHECKPOINT_ROLE, _checkpoint_target(repo, branch)
            )
        except Exception as error:  # a branch that cannot be read is for the owner to see
            self._escalate(found, repo, subject, f"could not be read ({type(error).__name__})")
            return
        stop_at: str | None = None
        limit = config.max_depth
        rewritten = False
        failed = False
        if checkpoint is not None:
            # How far the tip is from the checkpoint is GitHub's answer, not a guess: it bounds
            # the walk. An answer that cannot be had or understood judges nothing.
            try:
                compared: CompareResult | None = await github.compare(repo, checkpoint, tip)
            except Exception as error:
                compared = None
                self.logger.error("comparison failed", repo=repo, error=type(error).__name__)
            plan = plan_walk(compared, checkpoint, config.max_depth)
            if plan.nothing_to_judge:
                return
            stop_at, limit, rewritten = plan.stop_at, plan.limit, plan.rewritten
            failed = plan.comparison_failed
        complete = not failed
        if rewritten:
            # Recorded and escalated at once; the landings are still judged: from the merge base,
            # or, when the comparison failed, back the first sweep's depth from the tip.
            what = (
                f"{branch} could not be compared with the checkpoint {checkpoint}"
                if failed
                else f"{branch} no longer descends from the checkpoint {checkpoint}"
            )
            recorded = await self._record_unrevertable(
                found,
                repo,
                f"{branch} rewritten@{tip[:12]}",
                BreachKindType.REWRITTEN_BRANCH,
                f"{what}: it was rewritten",
                stamp,
            )
            complete = complete and recorded
        try:
            line, stopped = await self._first_parent_line(github, repo, tip, stop_at, limit)
        except Exception as error:
            self._escalate(found, repo, subject, f"could not be read ({type(error).__name__})")
            return
        landed = [commit.sha for commit in line]
        if checkpoint is not None and not checkpoint_reached(stopped, stop_at):
            # Ahead of the checkpoint but not along the branch's own line: not a history to judge
            # as ordinary landings. Recorded; the checkpoint does not move.
            await self._record_unrevertable(
                found,
                repo,
                f"{branch} line broken@{tip[:12]}",
                BreachKindType.REWRITTEN_BRANCH,
                f"{branch} first-parent line does not lead to {stop_at}",
                stamp,
            )
            complete = False
        try:
            pulls = {
                pull.merge_commit_sha: pull
                for pull in await github.merged_pulls_with_commits(repo, branch, frozenset(landed))
                if pull.merge_commit_sha is not None
            }
        except Exception as error:
            self._escalate(
                found, repo, subject, f"pull requests could not be read ({type(error).__name__})"
            )
            return
        for sha in landed:
            try:
                observation = await self._observe(github, repo, branch, sha, pulls.get(sha))
                verdict = judge_merge(
                    observation, config.mandate_login, config.own_repos, config.emergency_humans
                )
                if verdict is not MergeVerdictType.GUARDED:
                    complete = (
                        await self._answer(github, observation, verdict, stamp, found) and complete
                    )
            except Exception as error:
                complete = False
                self._escalate(
                    found,
                    repo,
                    sha,
                    f"the landing could not be recorded or answered ({type(error).__name__})",
                )
        if complete:
            try:
                await self._write_checkpoint(repo, branch, tip, stamp)
            except Exception as error:
                self._escalate(
                    found,
                    repo,
                    subject,
                    f"the checkpoint could not be written ({type(error).__name__})",
                )

    async def _first_parent_line(
        self, github: SweepGitHub, repo: str, tip: str, stop_at: str | None, limit: int
    ) -> tuple[list[BranchCommit], str | None]:
        """The landings from the tip back to, not including, `stop_at` (or the limit), and the
        commit the walk stopped on."""
        line: list[BranchCommit] = []
        current: str | None = tip
        while current is not None and not walk_complete(current, stop_at, len(line), limit):
            commit = await github.read_commit(repo, current)
            line.append(commit)
            current = commit.parents[0] if commit.parents else None
        return line, current

    async def _observe(
        self, github: SweepGitHub, repo: str, branch: str, sha: str, pull: PullMerge | None
    ) -> MergeObservation:
        head = pull.head_sha if pull else sha
        return MergeObservation(
            repo=repo,
            branch=branch,
            merge_commit=sha,
            head_sha=head,
            merged_by=pull.merged_by if pull else None,
            merged_at=pull.merged_at if pull else datetime.now(UTC),
            pull_number=pull.number if pull else None,
            node_id=pull.node_id if pull else None,
            statuses=await github.list_head_statuses(repo, head),
        )

    async def _answer(
        self,
        github: SweepGitHub,
        observation: MergeObservation,
        verdict: MergeVerdictType,
        stamp: VersionStamp,
        found: _Found,
    ) -> bool:
        """Record, escalate and answer one landing; True only when it is fully handled."""
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
        if recorded:
            found.findings.append(
                RecordedFinding(
                    kind=kind,
                    repo=observation.repo,
                    subject=observation.merge_commit,
                    detail=reason,
                )
            )
            self._escalate(found, observation.repo, observation.merge_commit, reason)
        if emergency:
            return True
        if observation.node_id is None or observation.pull_number is None:
            if recorded:
                self._escalate(
                    found,
                    observation.repo,
                    observation.merge_commit,
                    "no revert pull request: the commit is not a merged pull request",
                )
            return True
        opened = await self._ledger.latest_choice(
            MANDATE_ACTOR, REVERT_ROLE, observation.merge_commit
        )
        if not revert_due(True, opened is not None):
            return True
        revert = await github.open_revert_pull(observation.node_id)
        await self._remember_revert(observation, revert, stamp)
        found.reverts.append(
            OpenedRevert(
                repo=observation.repo, reverted_pull=observation.pull_number, revert_pull=revert
            )
        )
        return True

    async def _remember_revert(
        self, observation: MergeObservation, revert: int, stamp: VersionStamp
    ) -> None:
        text = f"{observation.repo}: revert pull request {revert} opened for {observation.merge_commit}"
        await self._write(REVERT_ROLE, observation.merge_commit, f"pull {revert}", text, stamp)

    async def _record_unrevertable(
        self,
        found: _Found,
        repo: str,
        target: str,
        kind: BreachKindType,
        reason: str,
        stamp: VersionStamp,
    ) -> bool:
        """Record and escalate a breach no pull request can revert."""
        try:
            recorded = await self._record(
                POLICY_BREACH_ROLE,
                kind,
                f"{repo}: {target}",
                f"{repo}: {reason}",
                MANDATE_ACTOR,
                stamp,
            )
        except Exception as error:
            self._escalate(found, repo, target, f"could not be recorded ({type(error).__name__})")
            return False
        if recorded:
            found.findings.append(
                RecordedFinding(kind=kind, repo=repo, subject=target, detail=reason)
            )
            self._escalate(found, repo, target, reason)
        return True

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
        if BYPASS_LIMIT not in found.limits:
            found.limits.append(BYPASS_LIMIT)
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
        await self._record_unrevertable(
            found,
            finding.repo,
            finding.subject,
            BreachKindType.GOVERNANCE_CHANGE,
            finding.reason,
            stamp,
        )

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
        return await self._write(role, target, kind.value, reason, stamp, f"acted by {seen_by}")

    async def _write(
        self,
        role: str,
        target: str,
        choice: str,
        reason: str,
        stamp: VersionStamp,
        extra: str | None = None,
    ) -> bool:
        record = DecisionRecord(
            actor=MANDATE_ACTOR,
            role=role,
            rung=RungType.L0,
            options_offered=(DecisionOption(option_id=choice, description=reason),),
            choice=choice,
            reasons=(reason,) if extra is None else (reason, extra),
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

    async def _write_checkpoint(
        self, repo: str, branch: str, tip: str, stamp: VersionStamp
    ) -> None:
        await self._write(
            CHECKPOINT_ROLE,
            _checkpoint_target(repo, branch),
            tip,
            f"{repo} {branch} was at {tip} when last swept",
            stamp,
        )

    def _escalate(self, found: _Found, repo: str, subject: str, reason: str) -> None:
        self.logger.error("policy escalation", repo=repo, subject=subject, reason=reason)
        found.escalations.append(SweepEscalation(repo=repo, subject=subject, reason=reason))


def _checkpoint_target(repo: str, branch: str) -> str:
    return f"{repo}/{branch}"
