"""Gets a deciding role's call, seals it into the ledger, and reveals it after signoff.

The call is asked for with one retry: a missing or invalid answer is asked for again once, and
a second miss counts as no call. Sealing joins the caller's transaction, so the gate state and
the sealing entry commit together. The ledger keeps only a digest; the call and its nonce are
handed back to the caller and never go to the pull request.

Reveal is allowed only when the caller states that the holder's signoff is recorded. W1 builds
the reading of the signoff itself; this service takes the fact as an explicit input.
"""

import secrets
from typing import Protocol
from uuid import UUID

from injector import inject
from sqlalchemy.ext.asyncio import AsyncSession

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.gates.brief import call_digest
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import GateBrief, RoleBrief, SealedCall
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import (
    CallRevealRecord,
    LedgerEntryType,
    SealedCallRecord,
    StoredLedgerEntry,
)
from src.models.role_output_models import DecidingRoleCall, read_role_output

CALL_ATTEMPTS = 2
"""The first ask and one retry."""


class DecidingRoleCallSource(Protocol):
    """Asks the deciding role for its call on a gate; returns its raw answer, or None."""

    async def request_call(self, brief: RoleBrief) -> str | None: ...


class SignoffNotRecordedError(BaseAppException):
    """The call was asked to be revealed before the holder's signoff was recorded."""

    def __init__(self) -> None:
        super().__init__(
            code="CALL_REVEAL_BEFORE_SIGNOFF",
            message="the deciding role's call is revealed only after the signoff is recorded",
            status_code=409,
        )


class SealedCallMismatchError(BaseAppException):
    """What was offered for reveal is not what the ledger sealed."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="SEALED_CALL_MISMATCH", message=detail, status_code=409)


class SealedCallService(BaseBusinessService):
    """Seals and reveals deciding-role calls."""

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

    async def obtain_call(
        self, source: DecidingRoleCallSource, brief: GateBrief
    ) -> DecidingRoleCall | None:
        """The role's call, asking again once when the first answer is missing or invalid.

        The role is shown the brief without the author's recommendation. A call that picks an
        option the brief does not offer is invalid.
        """
        offered = {option.option_id for option in brief.options}
        shown = brief.for_deciding_role()
        for _ in range(CALL_ATTEMPTS):
            call = read_role_output(DecidingRoleCall, await source.request_call(shown))
            if call is not None and call.option in offered:
                return call
        return None

    async def seal_in(
        self,
        session: AsyncSession,
        gate_id: UUID,
        head_sha: str,
        call: DecidingRoleCall | None,
        stamp: VersionStamp,
    ) -> SealedCall:
        """Hash the call into the ledger in the caller's transaction (no call: record that)."""
        nonce = None if call is None else secrets.token_hex(16)
        digest = None if call is None or nonce is None else call_digest(gate_id, call, nonce)
        entry = await self._ledger.append_sealed_call_in(
            session,
            SealedCallRecord(
                gate_id=gate_id, head_sha=head_sha, call_digest=digest, call=call, nonce=nonce
            ),
            stamp,
        )
        if entry.entry_hash is None:
            raise SealedCallMismatchError("the sealing entry has no hash")
        return SealedCall(gate_id=gate_id, sealed_entry_hash=entry.entry_hash)

    async def reveal(
        self, gate_id: UUID, signoff_recorded: bool, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Write the sealed call into the ledger, only once the holder's signoff is recorded.

        The call is read back from the sealing entry, so this works after a restart.
        """
        if not signoff_recorded:
            raise SignoffNotRecordedError()
        async with self._postgres.transaction() as session:
            entry = await self._ledger_repository.find_by_type_and_gate(
                session, LedgerEntryType.SEALED_CALL, gate_id
            )
            if entry is None or entry.entry_hash is None:
                raise SealedCallMismatchError("no call was sealed for this gate")
            record = SealedCallRecord.model_validate(entry.payload)
            if record.call is None or record.nonce is None:
                raise SealedCallMismatchError(
                    "this gate sealed no call, so there is nothing to reveal"
                )
            if record.call_digest != call_digest(gate_id, record.call, record.nonce):
                raise SealedCallMismatchError("the stored call does not match its digest")
            return await self._ledger.append_call_reveal_in(
                session,
                CallRevealRecord(
                    gate_id=gate_id,
                    sealed_entry_hash=entry.entry_hash,
                    call=record.call,
                    nonce=record.nonce,
                ),
                stamp,
            )
