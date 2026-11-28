"""Posts the required check mandate/gate-decision on a pull request's head.

Success only when the signoff matches the head (label, attested Approve, ready), the pull
request merges into the gate's own branch, no other open pull request into a governed branch
shares the head, the signer holds the gate at its rung and the signer's decision is in the
ledger. Anything else posts failure with the reason. Once the head is known, an error of any
kind (a failed read, an unknown state, a ledger fault) posts failure on that head rather than
leaving an earlier answer standing. After success the signoff is read again, and a signoff
that no longer holds is answered with failure. If even the pull request cannot be read, the
failure is logged and raised for escalation. There is no timeout and no default.
"""

from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.signoff_service import PullRequestReader, SignoffService
from src.exceptions.app_exceptions import BaseAppException
from src.logging import get_logger
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.signoff_models import (
    GOVERNED_BRANCHES,
    GateDecisionOutcome,
    GateDecisionStateType,
    GateRule,
    OpenPull,
)

logger = get_logger()


class GitHubGateClient(PullRequestReader, Protocol):
    """What the check needs from GitHub."""

    async def read_head_sha(self, ref: PullRequestRef) -> str: ...

    async def open_pulls_for_commit(self, repo: str, head_sha: str) -> tuple[OpenPull, ...]: ...

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
    """Evaluates one gate on one pull request and posts the result."""

    @inject
    def __init__(self, signoffs: SignoffService) -> None:
        super().__init__()
        self._signoffs = signoffs

    async def evaluate_and_post(
        self, github: GitHubGateClient, ref: PullRequestRef, rule: GateRule, stamp: VersionStamp
    ) -> GateDecisionOutcome:
        """Decide pass or fail by the rule, record the signoff, post on the head."""
        try:
            head = await github.read_head_sha(ref)
        except Exception as error:
            logger.error("pull request unreadable", repo=ref.repo, number=ref.number)
            raise GateUnreadableError(ref) from error
        try:
            outcome = await self._decide(github, ref, rule, stamp)
        except Exception as error:  # any fault once the head is known fails the check
            reason = f"the signoff could not be read or recorded ({type(error).__name__})"
            return await self._post(github, ref, head, GateDecisionStateType.FAILURE, reason, None)
        posted = await self._post(
            github, ref, outcome.head_sha, outcome.state, outcome.reason, outcome.signer
        )
        if posted.state is not GateDecisionStateType.SUCCESS:
            return posted
        return await self._confirm_still_holds(github, ref, rule, posted)

    async def _decide(
        self, github: GitHubGateClient, ref: PullRequestRef, rule: GateRule, stamp: VersionStamp
    ) -> GateDecisionOutcome:
        snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
        head = snapshot.head_sha
        signoff = assessment.signoff
        if signoff is None:
            return _outcome(GateDecisionStateType.FAILURE, head, assessment.reason or "no signoff")
        sharing = [
            pull
            for pull in await github.open_pulls_for_commit(ref.repo, head)
            if pull.ref != ref and pull.base_ref in GOVERNED_BRANCHES
        ]
        if sharing:
            numbers = ", ".join(f"#{pull.ref.number}" for pull in sharing)
            return _outcome(
                GateDecisionStateType.FAILURE,
                head,
                f"this commit is also the head of {numbers}, so one signoff cannot cover both",
            )
        await self._signoffs.record_signoff(signoff, rule, stamp)
        if not await self._signoffs.is_recorded(signoff, rule):
            return _outcome(
                GateDecisionStateType.FAILURE, head, "the decision is not in the ledger"
            )
        return _outcome(
            GateDecisionStateType.SUCCESS,
            head,
            f"{rule.label} signed by {signoff.signer} on this head and recorded",
            signoff.signer,
        )

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
            holds = (
                assessment.signoff is not None
                and snapshot.head_sha == posted.head_sha
                and assessment.signoff.signer == posted.signer
            )
            reason = assessment.reason or "the head moved or the signer changed"
        except Exception as error:
            holds = False
            reason = f"the signoff could not be read again ({type(error).__name__})"
        if holds:
            return posted
        return await self._post(
            github, ref, posted.head_sha, GateDecisionStateType.FAILURE,
            f"the signoff no longer holds: {reason}", None,
        )  # fmt: skip

    async def _post(
        self,
        github: GitHubGateClient,
        ref: PullRequestRef,
        head_sha: str,
        state: GateDecisionStateType,
        reason: str,
        signer: str | None,
    ) -> GateDecisionOutcome:
        await github.post_gate_decision(ref.repo, head_sha, state, reason)
        return _outcome(state, head_sha, reason, signer)


def _outcome(
    state: GateDecisionStateType, head_sha: str, reason: str, signer: str | None = None
) -> GateDecisionOutcome:
    return GateDecisionOutcome(state=state, head_sha=head_sha, reason=reason, signer=signer)
