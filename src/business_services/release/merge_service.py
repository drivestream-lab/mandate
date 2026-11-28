"""Applies the signoff and merges where Mandate's App is the signer; leaves the merge to a person's
merger everywhere else.

At L0 and L1 Mandate never signs or merges: it only runs the check, and the merger the workflow
names merges once the check passes. At L2 and L3 the deciding role has signed in the ledger and
Mandate's App applies the three signoff artifacts (the gate's label, an Approve carrying the
attestation, the pull request ready), runs the check, and only when it passes merges through the
merge API with the sha pinned to the head the check passed on. GitHub then refuses the merge
unless the head is still exactly that commit and its required check passes. A merge GitHub
refuses is reported, never retried or worked around.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol

from injector import inject
from pydantic import BaseModel, ConfigDict

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.gate_decision_check_service import (
    GateDecisionCheckService,
    GitHubGateClient,
    WaveEvidence,
)
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.engine.gates.merge_rules import (
    LEFT_TO_MERGER,
    attestation_body,
    decided_attestation,
    mandate_merges,
    merge_decision_role,
    signoff_problem,
    void_after_decision,
)
from src.engine.gates.voiding_rules import revised_role, stale_role
from src.infra_services.github_app_service import GitHubError
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.signoff_models import (
    ArtifactLink,
    DecisionLink,
    GateDecisionOutcome,
    GateDecisionStateType,
    MANDATE_ACTOR,
    GateRule,
)


class MergeClient(GitHubGateClient, Protocol):
    """What applying a signoff and merging need from GitHub, besides the check's own calls."""

    async def approve_pull(self, ref: PullRequestRef, head_sha: str, body: str) -> None: ...

    async def mark_pull_ready(self, ref: PullRequestRef) -> None: ...

    async def merge_pull(self, ref: PullRequestRef, sha: str) -> str: ...


class MergeStateType(StrEnum):
    """What came of asking Mandate to settle a gate's merge."""

    MERGED = "merged"
    LEFT_TO_MERGER = "left_to_merger"
    NOT_SIGNED = "not_signed"
    CHECK_FAILED = "check_failed"
    MERGE_REFUSED = "merge_refused"


class MergeOutcome(BaseModel):
    """The result: the state, why, the check's outcome when it ran, and the merge commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: MergeStateType
    reason: str
    check: GateDecisionOutcome | None = None
    merge_commit: str | None = None


class MergeService(BaseBusinessService):
    """Settles a gate's merge by rung."""

    @inject
    def __init__(self, checks: GateDecisionCheckService, ledger: LedgerAppendService) -> None:
        super().__init__()
        self._checks = checks
        self._ledger = ledger

    async def settle(
        self,
        github: MergeClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule] = (),
        links: Sequence[ArtifactLink] = (),
        decision_links: Sequence[DecisionLink] = (),
        wave: WaveEvidence | None = None,
    ) -> MergeOutcome:
        """Run the check and, at L2 and L3 only, sign as Mandate's App and merge.

        At L2 and L3 the deciding role's recorded approve for this repository, pull request, head
        and gate is read from the ledger and its attestation is what Mandate's App signs with;
        without that record, or with any other choice, nothing is applied.
        """
        if not mandate_merges(rule.rung):
            checked = await self._check(
                github, ref, rule, stamp, all_rules, links, decision_links, wave
            )
            return MergeOutcome(
                state=MergeStateType.LEFT_TO_MERGER, reason=LEFT_TO_MERGER, check=checked
            )
        if rule.deciding_role is None:
            return MergeOutcome(
                state=MergeStateType.NOT_SIGNED, reason="the gate names no deciding role"
            )
        snapshot = await github.read_pull_request(ref)
        record = await self._ledger.latest_decision_record(
            rule.deciding_role, merge_decision_role(rule, ref), snapshot.head_sha
        )
        attestation = decided_attestation(record)
        if isinstance(attestation, str) or record is None:
            return MergeOutcome(
                state=MergeStateType.NOT_SIGNED,
                reason=attestation if isinstance(attestation, str) else "no decision",
            )
        decided_at = await self._ledger.latest_decision_sequence(
            rule.deciding_role, merge_decision_role(rule, ref), snapshot.head_sha
        )
        voids = [
            await self._ledger.latest_decision_sequence(MANDATE_ACTOR, role, snapshot.head_sha)
            for role in (revised_role(rule), stale_role(rule))
        ]
        voided = void_after_decision(decided_at, voids) if decided_at is not None else "no decision"
        if voided is not None:
            return MergeOutcome(state=MergeStateType.NOT_SIGNED, reason=voided)
        problem = signoff_problem(snapshot, rule, attestation)
        if problem is not None:
            return MergeOutcome(state=MergeStateType.NOT_SIGNED, reason=problem)
        if rule.label not in snapshot.labels:
            await github.add_label(ref, rule.label)
        await github.approve_pull(ref, snapshot.head_sha, attestation_body(attestation))
        if snapshot.is_draft:
            await github.mark_pull_ready(ref)
        checked = await self._check(
            github, ref, rule, stamp, all_rules, links, decision_links, wave
        )
        if checked.state is not GateDecisionStateType.SUCCESS:
            return MergeOutcome(
                state=MergeStateType.CHECK_FAILED, reason=checked.reason, check=checked
            )
        try:
            merged = await github.merge_pull(ref, checked.head_sha)
        except GitHubError as error:
            self.logger.error("merge refused", repo=ref.repo, number=ref.number, error=str(error))
            return MergeOutcome(
                state=MergeStateType.MERGE_REFUSED,
                reason=f"GitHub refused the merge pinned to {checked.head_sha}: {error}",
                check=checked,
            )
        return MergeOutcome(
            state=MergeStateType.MERGED,
            reason=f"merged at {checked.head_sha}",
            check=checked,
            merge_commit=merged,
        )

    async def _check(
        self,
        github: MergeClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule],
        links: Sequence[ArtifactLink],
        decision_links: Sequence[DecisionLink],
        wave: WaveEvidence | None,
    ) -> GateDecisionOutcome:
        return await self._checks.evaluate_and_post(
            github, ref, rule, stamp, all_rules, links, decision_links, wave
        )
