"""Reads a gate's signoff on the current head and records the signer's decision in the ledger.

Reading is a comparison, not a judgement: the pull request's label, attested Approve and ready
state are checked against the gate's rule by a pure function. Recording writes the signer's
decision once per head (a repeat finds the entry already there), so the check can require that
the decision is in the ledger before it passes. This service only reads GitHub and writes the
ledger; it never signs.
"""

from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.gates.signoff_rules import assess_signoff
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, StoredLedgerEntry
from src.models.signoff_models import (
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
    def __init__(
        self,
        postgres_service: PostgresService,
        ledger: LedgerAppendService,
        ledger_repository: LedgerRepository,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._ledger = ledger
        self._ledger_repository = ledger_repository

    async def read_signoff(
        self, reader: PullRequestReader, ref: PullRequestRef, rule: GateRule
    ) -> tuple[PullRequestSnapshot, SignoffAssessment]:
        """The pull request as it is now, and its signoff on that head or why there is none."""
        snapshot = await reader.read_pull_request(ref)
        return snapshot, assess_signoff(snapshot, rule)

    async def is_recorded(self, signoff: SignoffReading, rule: GateRule) -> bool:
        """True when the ledger already holds this signer's decision on this head."""
        async with self._postgres.get_session() as session:
            found = await self._ledger_repository.find_decision(
                session, signoff.signer, rule.label, signoff.head_sha
            )
        return found is not None

    async def record_signoff(
        self, signoff: SignoffReading, rule: GateRule, stamp: VersionStamp
    ) -> StoredLedgerEntry | None:
        """Write the signer's decision unless it is already there; None when it was."""
        if await self.is_recorded(signoff, rule):
            return None
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
        return await self._ledger.append_decision(record, stamp)
