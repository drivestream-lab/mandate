"""Reads a gate's signoff on the current head and records the signer's decision in the ledger.

Reading is a comparison, not a judgement: the pull request's label, attested Approve and ready
state are checked against the gate's rule by a pure function. Recording writes the signer's
decision once per head (a repeat finds the entry already there), so the check can require that
the decision is in the ledger before it passes. This service only reads GitHub and writes the
ledger; it never signs.
"""

from datetime import UTC, datetime
from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.engine.gates.signoff_rules import assess_signoff
from src.engine.gates.voiding_rules import (
    EDITED_FAILURE_REASON,
    NOT_PINNED_REASON,
    attestation_edited_role,
    attestation_evidence,
    attestation_key,
    attestation_role,
    pinned_digest,
    revised_role,
    stale_role,
    voided_review_ids,
    without_reviews,
)
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, StoredLedgerEntry
from src.models.signoff_models import (
    MANDATE_ACTOR,
    GateRule,
    PullRequestSnapshot,
    SignoffAssessment,
    SignoffReading,
)

SIGNOFF_CHOICE = "signed"
_WORKFLOW_VERSION = "gate-signoff/1"
_IDENTITY_VERSION = "github-identity"


class PullRequestReader(Protocol):
    """Reads a pull request from GitHub."""

    async def read_pull_request(self, ref: PullRequestRef) -> PullRequestSnapshot: ...


class SignoffService(BaseBusinessService):
    """Reads signoffs and records them."""

    @inject
    def __init__(self, ledger: LedgerAppendService) -> None:
        super().__init__()
        self._ledger = ledger

    async def read_signoff(
        self, reader: PullRequestReader, ref: PullRequestRef, rule: GateRule
    ) -> tuple[PullRequestSnapshot, SignoffAssessment]:
        """The pull request as it is now, and its signoff on that head or why there is none.

        Approves that a void on this head names are left out, so a signoff is looked for among
        the Approves no void names.
        """
        snapshot = await reader.read_pull_request(ref)
        voided: set[int] = set()
        for role in (revised_role(rule), stale_role(rule)):
            for record in await self._ledger.decision_records(
                MANDATE_ACTOR, role, snapshot.head_sha
            ):
                voided |= voided_review_ids(record.evidence)
        assessment = assess_signoff(without_reviews(snapshot, frozenset(voided)), rule)
        if assessment.signoff is None and voided:
            ids = ", ".join(str(item) for item in sorted(voided))
            return snapshot, SignoffAssessment(
                signoff=None,
                reason=f"{assessment.reason}; Approves {ids} on this head were voided",
            )
        return snapshot, assessment

    async def attestation_failure(
        self, signoff: SignoffReading, rule: GateRule, stamp: VersionStamp, may_record: bool
    ) -> str | None:
        """The reason the signed Approve body is no longer the one first seen, or None.

        The first check pins the SHA-256 of the exact body in the ledger. Every later check
        compares the live body with it; a difference is recorded as an edit and fails the check,
        and an edit once recorded for a review fails it for good.
        """
        key = attestation_key(signoff.head_sha, signoff.review_id)
        if await self._ledger.latest_choice(MANDATE_ACTOR, attestation_edited_role(rule), key):
            return EDITED_FAILURE_REASON
        pinned = await self._ledger.latest_decision_record(
            signoff.signer, attestation_role(rule), key
        )
        if pinned is None:
            if not may_record:
                return NOT_PINNED_REASON
            await self._write(
                signoff, rule, signoff.signer, attestation_role(rule), key, "pinned", stamp
            )
            return None
        if pinned_digest(pinned.evidence) == signoff.body_digest:
            return None
        await self._write(
            signoff, rule, MANDATE_ACTOR, attestation_edited_role(rule), key, "edited", stamp
        )
        return EDITED_FAILURE_REASON

    async def _write(
        self,
        signoff: SignoffReading,
        rule: GateRule,
        actor: str,
        role: str,
        key: str,
        choice: str,
        stamp: VersionStamp,
    ) -> None:
        record = DecisionRecord(
            actor=actor,
            role=role,
            rung=rule.rung,
            options_offered=(DecisionOption(option_id=choice, description=choice),),
            choice=choice,
            reasons=(f"the body of review {signoff.review_id} as first seen",),
            evidence=attestation_evidence(signoff.review_id, signoff.body_digest),
            target_version=key,
            workflow_version=_WORKFLOW_VERSION,
            model_version=_IDENTITY_VERSION,
            decided_at=datetime.now(UTC),
        )
        await self._ledger.record_decision_once(record, stamp, "the body changed again")

    async def is_recorded(self, signoff: SignoffReading, rule: GateRule) -> bool:
        """True when the ledger holds this signer's decision on this head."""
        choice = await self._ledger.latest_choice(signoff.signer, rule.label, signoff.head_sha)
        return choice == SIGNOFF_CHOICE

    async def record_signoff(
        self,
        signoff: SignoffReading,
        rule: GateRule,
        stamp: VersionStamp,
    ) -> StoredLedgerEntry | None:
        """Write the signer's decision once per head; None when it was already there."""
        record = DecisionRecord(
            actor=signoff.signer,
            role=rule.label,
            rung=rule.rung,
            options_offered=(
                DecisionOption(option_id=SIGNOFF_CHOICE, description="Sign the gate on this head"),
            ),
            choice=SIGNOFF_CHOICE,
            reasons=(f"{signoff.label} applied, Approve with attestation, pull request ready",),
            evidence=(),
            target_version=signoff.head_sha,
            workflow_version=_WORKFLOW_VERSION,
            model_version=_IDENTITY_VERSION,
            decided_at=signoff.signed_at,
        )
        return await self._ledger.record_decision_once(
            record, stamp, "the signoff on this head changed"
        )
