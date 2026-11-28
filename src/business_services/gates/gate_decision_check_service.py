"""Posts the required check mandate/gate-decision on a pull request's head.

Success only when the signoff matches the head (label, attested Approve, ready), the pull
request merges into the gate's own branch, no other open pull request into a governed branch
has this commit as its head, the signer holds the gate at its rung and the signer's decision
is in the ledger. Anything else posts failure with the reason. Once the head is known, an
error of any kind posts failure on that head rather than leaving an earlier answer standing.
After success the signoff is read again, and a signoff that no longer holds is answered with
failure. What to post is decided by the pure rules in src/engine/gates; this service reads
and posts. A pull request that cannot be read at all is logged and raised.

recheck_open_gates runs the same evaluation over every open pull request into a governed
branch, so a retarget, a reopened pull request or a shared head is answered with failure
without waiting for the pull request's own events. It is called on a schedule by the workflow
that runs Mandate's polling; nothing schedules it yet.
"""

from collections.abc import Sequence
from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.signoff_service import PullRequestReader, SignoffService
from src.engine.gates.gate_decision_rules import (
    failure_after_fault,
    ambiguous_gate,
    choose_rule,
    more_than_one_gate_label,
    not_recorded_for_recheck,
    outcome_after_recording,
    refusal_for,
    sharing_pulls,
    withdrawal_after_fault,
    withdrawal_for,
)
from src.exceptions.app_exceptions import BaseAppException
from src.logging import get_logger
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.signoff_models import (
    GOVERNED_BRANCHES,
    EscalationNote,
    GateDecisionOutcome,
    GateDecisionStateType,
    GateRule,
    OpenPull,
    RecheckReport,
)

logger = get_logger()


class GitHubGateClient(PullRequestReader, Protocol):
    """What the check needs from GitHub."""

    async def read_head_sha(self, ref: PullRequestRef) -> str: ...

    async def list_open_pulls(self, repo: str, base: str) -> tuple[OpenPull, ...]: ...

    async def post_gate_decision(
        self, repo: str, head_sha: str, state: GateDecisionStateType, description: str
    ) -> None: ...


class GateUnreadableError(BaseAppException):
    """The pull request could not be read at all, so no head exists to post a failure on."""

    def __init__(self, ref: PullRequestRef) -> None:
        super().__init__(
            code="GATE_PULL_REQUEST_UNREADABLE",
            message=f"{ref.repo}#{ref.number} could not be read; escalate",
            status_code=502,
        )


class GateDecisionCheckService(BaseBusinessService):
    """Evaluates gates on pull requests and posts the results."""

    @inject
    def __init__(self, signoffs: SignoffService) -> None:
        super().__init__()
        self._signoffs = signoffs

    async def evaluate_and_post(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule] = (),
    ) -> GateDecisionOutcome:
        """Decide pass or fail by the rule, record the signoff, post on the head.

        `all_rules` are the gates configured for the repo; a pull request that carries the
        labels of two gates of its branch fails.
        """
        return await self._evaluate(github, ref, rule, stamp, all_rules or (rule,), True)

    async def _evaluate(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule],
        may_record: bool,
    ) -> GateDecisionOutcome:
        try:
            head = await github.read_head_sha(ref)
        except Exception as error:
            logger.error("pull request unreadable", repo=ref.repo, number=ref.number)
            raise GateUnreadableError(ref) from error
        try:
            outcome = await self._decide(github, ref, rule, stamp, all_rules, may_record)
        except Exception as error:  # any fault once the head is known fails the check
            return await self._post(github, ref, failure_after_fault(head, type(error).__name__))
        posted = await self._post(github, ref, outcome)
        if posted.state is not GateDecisionStateType.SUCCESS:
            return posted
        return await self._confirm_still_holds(github, ref, rule, posted)

    async def recheck_open_gates(
        self,
        github: GitHubGateClient,
        repos: Sequence[str],
        rules: Sequence[GateRule],
        stamp: VersionStamp,
    ) -> RecheckReport:
        """Re-evaluate every open pull request into a governed branch of these repos.

        A pull request that cannot be read, or a list that cannot be read, is logged as an
        error and returned as an escalation; the pass carries on with the rest.
        """
        outcomes: list[GateDecisionOutcome] = []
        escalations: list[EscalationNote] = []
        for repo in repos:
            for branch in sorted(GOVERNED_BRANCHES):
                try:
                    pulls = await github.list_open_pulls(repo, branch)
                except Exception as error:
                    note = EscalationNote(
                        repo=repo,
                        number=None,
                        reason=f"open pull requests into {branch} could not be listed "
                        f"({type(error).__name__})",
                    )
                    logger.error("escalation", repo=repo, reason=note.reason)
                    escalations.append(note)
                    continue
                for pull in pulls:
                    await self._recheck_one(github, pull, rules, stamp, outcomes, escalations)
        return RecheckReport(outcomes=tuple(outcomes), escalations=tuple(escalations))

    async def _recheck_one(
        self,
        github: GitHubGateClient,
        pull: OpenPull,
        rules: Sequence[GateRule],
        stamp: VersionStamp,
        outcomes: list[GateDecisionOutcome],
        escalations: list[EscalationNote],
    ) -> None:
        chosen = choose_rule(pull, rules)
        try:
            if isinstance(chosen, GateDecisionOutcome):
                await github.post_gate_decision(
                    pull.ref.repo, pull.head_sha, chosen.state, chosen.reason
                )
                outcomes.append(chosen)
            else:
                # The re-check only downgrades or re-confirms: it never records a decision.
                outcomes.append(await self._evaluate(github, pull.ref, chosen, stamp, rules, False))
        except Exception as error:  # includes GateUnreadableError: a person must look
            note = EscalationNote(
                repo=pull.ref.repo,
                number=pull.ref.number,
                reason=f"the gate could not be re-evaluated ({type(error).__name__})",
            )
            logger.error(
                "escalation", repo=pull.ref.repo, number=pull.ref.number, reason=note.reason
            )
            escalations.append(note)

    async def _decide(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule],
        may_record: bool,
    ) -> GateDecisionOutcome:
        snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
        head = snapshot.head_sha
        if more_than_one_gate_label(snapshot.labels, snapshot.base_ref, all_rules):
            return ambiguous_gate(head)
        candidates: list[OpenPull] = []
        for branch in sorted(GOVERNED_BRANCHES):
            candidates += await github.list_open_pulls(ref.repo, branch)
        refusal = refusal_for(head, assessment, sharing_pulls(candidates, head, ref))
        signoff = assessment.signoff
        if refusal is not None or signoff is None:
            return refusal or failure_after_fault(head, "NoSignoff")
        if may_record:
            await self._signoffs.record_signoff(signoff, rule, stamp)
        elif not await self._signoffs.is_recorded(signoff, rule):
            return not_recorded_for_recheck(head, rule)
        recorded = await self._signoffs.is_recorded(signoff, rule)
        return outcome_after_recording(head, rule, signoff, recorded)

    async def _confirm_still_holds(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        posted: GateDecisionOutcome,
    ) -> GateDecisionOutcome:
        """Read the signoff again after posting success; withdraw the success if it is gone."""
        try:
            snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
            withdrawal = withdrawal_for(posted, snapshot.head_sha, assessment)
        except Exception as error:
            withdrawal = withdrawal_after_fault(posted, type(error).__name__)
        if withdrawal is None:
            return posted
        return await self._post(github, ref, withdrawal)

    async def _post(
        self, github: GitHubGateClient, ref: PullRequestRef, outcome: GateDecisionOutcome
    ) -> GateDecisionOutcome:
        await github.post_gate_decision(ref.repo, outcome.head_sha, outcome.state, outcome.reason)
        return outcome
