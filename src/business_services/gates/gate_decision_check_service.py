"""Posts the required check mandate/gate-decision on a pull request's head.

Success only when the signoff matches the head (label, attested Approve, ready), its signer
holds the gate at its rung, and the signer's decision is in the ledger. Anything else posts
failure with the reason, including anything Mandate cannot read or record. There is no
timeout and no default: a gate nobody has signed fails.
"""

from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.signoff_service import PullRequestReader, SignoffService
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.signoff_models import GateDecisionOutcome, GateDecisionStateType, GateRule


class GateDecisionPoster(Protocol):
    """Posts mandate/gate-decision on a head commit."""

    async def post_gate_decision(
        self, repo: str, head_sha: str, state: GateDecisionStateType, description: str
    ) -> None: ...


class GitHubGateClient(PullRequestReader, GateDecisionPoster, Protocol):
    """What the check needs from GitHub: read a pull request and post the check."""


class GateDecisionCheckService(BaseBusinessService):
    """Evaluates one gate on one pull request and posts the result."""

    @inject
    def __init__(self, signoffs: SignoffService) -> None:
        super().__init__()
        self._signoffs = signoffs

    async def evaluate_and_post(
        self, github: GitHubGateClient, ref: PullRequestRef, rule: GateRule, stamp: VersionStamp
    ) -> GateDecisionOutcome:
        """Read the head, decide pass or fail by the rule, record, and post on that head.

        A read that fails raises: nothing is posted for a head Mandate could not read.
        """
        snapshot, assessment = await self._signoffs.read_signoff(github, ref, rule)
        signoff = assessment.signoff
        if signoff is None:
            return await self._post(
                github, ref, snapshot.head_sha, GateDecisionStateType.FAILURE,
                assessment.reason or "no signoff", None,
            )  # fmt: skip
        try:
            await self._signoffs.record_signoff(signoff, rule, stamp)
            recorded = await self._signoffs.is_recorded(signoff, rule)
        except Exception as error:  # the ledger could not be written or read: fail, never pass
            reason = f"the decision could not be recorded in the ledger ({type(error).__name__})"
            return await self._post(
                github, ref, snapshot.head_sha, GateDecisionStateType.FAILURE, reason, None
            )
        if not recorded:
            return await self._post(
                github, ref, snapshot.head_sha, GateDecisionStateType.FAILURE,
                "the decision is not in the ledger", None,
            )  # fmt: skip
        return await self._post(
            github, ref, snapshot.head_sha, GateDecisionStateType.SUCCESS,
            f"{rule.label} signed by {signoff.signer} on this head and recorded", signoff.signer,
        )  # fmt: skip

    async def _post(
        self,
        github: GateDecisionPoster,
        ref: PullRequestRef,
        head_sha: str,
        state: GateDecisionStateType,
        reason: str,
        signer: str | None,
    ) -> GateDecisionOutcome:
        await github.post_gate_decision(ref.repo, head_sha, state, reason)
        return GateDecisionOutcome(state=state, head_sha=head_sha, reason=reason, signer=signer)
