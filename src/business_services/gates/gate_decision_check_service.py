"""Posts the required check mandate/gate-decision on a pull request's head.

Success only when the signoff matches the head (label, attested Approve, ready), the pull
request merges into the gate's own branch, no other open pull request into a governed branch
has this commit as its head, the signer holds the gate at its rung and the signer's decision
is in the ledger. Anything else posts failure with the reason. Once the head is known, an
error of any kind posts failure on that head rather than leaving an earlier answer standing.
For a wave gate the check also needs run-signed evidence for that exact head (the caller
supplies what the evidence must match). A head that moved after signoff, or an upstream pull request that changed after it, voids the
signoff in the ledger (the -revised and -stale labels only show it), and a recorded no on a linked
artifact fails the next merge downstream of it. After success the signoff is read again, and a signoff that no longer holds is answered with
failure. What to post is decided by the pure rules in src/engine/gates; this service reads
and posts. A pull request that cannot be read at all is logged and raised.

recheck_open_gates runs the same evaluation over every open pull request into a governed
branch, so a retarget, a reopened pull request or a shared head is answered with failure
without waiting for the pull request's own events. It is called on a schedule by the workflow
that runs Mandate's polling; nothing schedules it yet.
"""

from collections.abc import Mapping, Sequence
from typing import NamedTuple, Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.signoff_service import PullRequestReader, SignoffService
from src.business_services.gates.signoff_voiding_service import (
    LabelClient,
    SignoffVoidingService,
)
from src.engine.gates.gate_decision_rules import (
    failure,
    failure_after_fault,
    ambiguous_gate,
    choose_rule,
    evidence_failure,
    wave_without_evidence,
    evidence_repository_failure,
    with_evidence,
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
from src.models.evidence_models import (
    EvidenceRefusal,
    EvidenceTarget,
    VerifiedEvidence,
    WaveEvidenceSpec,
)
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.signoff_models import (
    GOVERNED_BRANCHES,
    EscalationNote,
    GateDecisionOutcome,
    GateDecisionStateType,
    ArtifactLink,
    DecisionLink,
    GateRule,
    OpenPull,
    RecheckReport,
    UpstreamHead,
)

logger = get_logger()


class EvidenceChecker(Protocol):
    """Accepts run-signed evidence for a commit or refuses it."""

    async def verify(self, target: EvidenceTarget) -> VerifiedEvidence: ...


class WaveEvidence(NamedTuple):
    """The gates that are waves, by label, with what the caller fixed about each one's evidence
    (from the recorded spec signoff, never from the commit under test), and who checks it."""

    checker: EvidenceChecker
    specs: Mapping[str, WaveEvidenceSpec]
    owner: str


class _Scope(NamedTuple):
    """What an evaluation knows beyond the pull request: the gates, the links and the evidence."""

    rules: Sequence[GateRule]
    links: tuple[ArtifactLink, ...]
    decision_links: tuple[DecisionLink, ...]
    wave: WaveEvidence | None = None


class GitHubGateClient(PullRequestReader, LabelClient, Protocol):
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
    def __init__(self, signoffs: SignoffService, voiding: SignoffVoidingService) -> None:
        super().__init__()
        self._signoffs = signoffs
        self._voiding = voiding

    async def evaluate_and_post(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        all_rules: Sequence[GateRule] = (),
        links: Sequence[ArtifactLink] = (),
        decision_links: Sequence[DecisionLink] = (),
        wave: WaveEvidence | None = None,
    ) -> GateDecisionOutcome:
        """Decide pass or fail by the rule, record the signoff, post on the head.

        `all_rules` are the gates configured for the repo; a pull request that carries the
        labels of two gates of its branch fails. `links` name the pull requests upstream of
        this one, and `decision_links` the artifacts whose recorded no fails this merge. For a
        gate named in `wave` the check also needs run-signed evidence for this exact head, read
        again on every evaluation, so a head that moved fails until its own evidence is there.
        """
        scope = _Scope(all_rules or (rule,), tuple(links), tuple(decision_links), wave)
        return await self._evaluate(github, ref, rule, stamp, scope, True)

    async def _evaluate(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        rule: GateRule,
        stamp: VersionStamp,
        scope: _Scope,
        may_record: bool,
    ) -> GateDecisionOutcome:
        try:
            head = await github.read_head_sha(ref)
        except Exception as error:
            logger.error("pull request unreadable", repo=ref.repo, number=ref.number)
            raise GateUnreadableError(ref) from error
        try:
            outcome = await self._decide(github, ref, rule, stamp, scope, may_record)
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
        links: Sequence[ArtifactLink] = (),
        decision_links: Sequence[DecisionLink] = (),
        wave: WaveEvidence | None = None,
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
                    await self._recheck_one(
                        github,
                        pull,
                        _Scope(tuple(rules), tuple(links), tuple(decision_links), wave),
                        stamp,
                        outcomes,
                        escalations,
                    )
        return RecheckReport(outcomes=tuple(outcomes), escalations=tuple(escalations))

    async def _recheck_one(
        self,
        github: GitHubGateClient,
        pull: OpenPull,
        scope: _Scope,
        stamp: VersionStamp,
        outcomes: list[GateDecisionOutcome],
        escalations: list[EscalationNote],
    ) -> None:
        chosen = choose_rule(pull, scope.rules)
        try:
            if isinstance(chosen, GateDecisionOutcome):
                await github.post_gate_decision(
                    pull.ref.repo, pull.head_sha, chosen.state, chosen.reason
                )
                outcomes.append(chosen)
            else:
                # The re-check only downgrades or re-confirms: it never records a decision.
                outcomes.append(await self._evaluate(github, pull.ref, chosen, stamp, scope, False))
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
        scope: _Scope,
        may_record: bool,
    ) -> GateDecisionOutcome:
        all_rules = scope.rules
        snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
        head = snapshot.head_sha
        await self._signoffs.record_edited_approves(snapshot, rule, stamp)
        if more_than_one_gate_label(snapshot.labels, snapshot.base_ref, all_rules):
            return ambiguous_gate(head)
        candidates: list[OpenPull] = []
        for branch in sorted(GOVERNED_BRANCHES):
            candidates += await github.list_open_pulls(ref.repo, branch)
        refusal = refusal_for(head, assessment, sharing_pulls(candidates, head, ref))
        signoff = assessment.signoff
        if signoff is None:
            await self._voiding.void_superseded_signoff(github, snapshot, rule, stamp)
        if refusal is not None or signoff is None:
            return refusal or failure_after_fault(head, "NoSignoff")
        upstream_now = [
            UpstreamHead(upstream=link.upstream, head_sha=await github.read_head_sha(link.upstream))
            for link in scope.links
            if link.downstream == ref
        ]
        stale: str | None = None
        for _ in range(len(snapshot.reviews) + 1):
            if may_record:
                await self._signoffs.record_signoff(signoff, rule, stamp)
            elif not await self._signoffs.is_recorded(signoff, rule):
                return not_recorded_for_recheck(head, rule)
            if not await self._signoffs.is_recorded(signoff, rule):
                return outcome_after_recording(head, rule, signoff, False)
            edited = await self._signoffs.attestation_failure(signoff, rule, stamp, may_record)
            if edited is not None:
                return failure(head, edited)
            stale = await self._voiding.stale_failure(
                github, snapshot, signoff, rule, upstream_now, stamp
            )
            if stale is None:
                break
            # The stale void names this Approve; another holder's Approve may still stand.
            snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
            if snapshot.head_sha != head or assessment.signoff is None:
                return failure(head, stale)
            signoff = assessment.signoff
        else:
            return failure(head, stale or failure_after_fault(head, "StaleLoop").reason)
        unresolved = await self._voiding.unresolved_no_failure(github, ref, scope.decision_links)
        if unresolved is not None:
            return failure(head, unresolved)
        passed = outcome_after_recording(head, rule, signoff, True)
        wave_refusal, verified = await self._wave_evidence(scope, ref, rule, head)
        if wave_refusal is not None:
            return wave_refusal
        await self._voiding.clear_labels(github, snapshot, rule)
        if verified is None:
            return passed
        return with_evidence(passed, verified.tests, verified.run_id, verified.run_attempt)

    async def _wave_evidence(
        self, scope: _Scope, ref: PullRequestRef, rule: GateRule, head: str
    ) -> tuple[GateDecisionOutcome | None, VerifiedEvidence | None]:
        """For a wave gate: the failure to post, or the evidence accepted for this exact head.

        A refusal names its reason; any other fault propagates and fails the check on the head.
        """
        if scope.wave is None or rule.label not in scope.wave.specs:
            if rule.is_wave:
                return wave_without_evidence(head, rule), None
            return None, None
        spec = scope.wave.specs[rule.label]
        elsewhere = evidence_repository_failure(
            head, spec.repository, f"{scope.wave.owner}/{ref.repo}"
        )
        if elsewhere is not None:
            return elsewhere, None
        try:
            return None, await scope.wave.checker.verify(spec.target_for(head))
        except EvidenceRefusal as refusal:
            return evidence_failure(head, refusal.reason), None

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
