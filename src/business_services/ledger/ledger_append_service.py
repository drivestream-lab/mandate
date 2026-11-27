"""Appends decisions and corrections to the ledger, and checks the chain.

Every append runs in one transaction: take the chain lock, read the head, check the head still
matches its own hash, seal the new entry onto it, insert. The lock makes two appends take turns,
so each reads the head the other left. The database also refuses a second entry after the same
entry (a unique index on previous_hash), so a writer that skipped the lock fails rather than
forks the chain.

The append can also join the caller's transaction (append_decision_in, append_correction_in), so
a state change, its ledger entry and its outbox message commit or roll back together. The lock
and the head checks then run inside that transaction and are released when it ends.

The writer refuses to extend a head that does not link back to the genesis hash (an orphan head,
or a loop), as it refuses a head that does not match its own hash: verification reports both,
and nothing new is added on top of a chain that is already broken.

A correction is a new entry that names the original by its hash. Nothing is ever updated.
"""

from uuid import UUID, uuid4

from injector import inject
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from src.business_services.base_business_service import BaseBusinessService
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.ledger.hash_chain import entry_hash_problem, seal_entry, verify_chain
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.postgres_service import PostgresService
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import (
    GENESIS_HASH,
    ChainAnchor,
    ChainVerification,
    CorrectionRecord,
    DecisionRecord,
    LedgerEntryDraft,
    LedgerEntryType,
    StoredLedgerEntry,
)


class LedgerHeadUnverifiableError(BaseAppException):
    """The latest entry does not match its own hash, so nothing is appended after it."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="LEDGER_HEAD_UNVERIFIABLE", message=detail, status_code=500)


class LedgerHeadOrphanError(BaseAppException):
    """The latest entry does not link back to genesis, so nothing is appended after it."""

    def __init__(self) -> None:
        super().__init__(
            code="LEDGER_HEAD_ORPHAN",
            message="the latest ledger entry does not link back to the start of the chain",
            status_code=500,
        )


class CorrectedEntryNotFoundError(BaseAppException):
    """A correction named an entry hash that is not in the ledger."""

    def __init__(self, entry_hash: str) -> None:
        super().__init__(
            code="LEDGER_CORRECTED_ENTRY_NOT_FOUND",
            message=f"no ledger entry has hash {entry_hash}",
            status_code=404,
        )


def build_decision_draft(
    record: DecisionRecord, stamp: VersionStamp, entry_id: UUID
) -> LedgerEntryDraft:
    """Turn a decision record into a draft entry of type decision."""
    return LedgerEntryDraft(
        entry_id=entry_id,
        entry_type=LedgerEntryType.DECISION,
        payload=_payload(record),
        version_stamp=stamp,
    )


def build_correction_draft(
    record: CorrectionRecord, stamp: VersionStamp, entry_id: UUID
) -> LedgerEntryDraft:
    """Turn a correction record into a draft entry of type correction."""
    return LedgerEntryDraft(
        entry_id=entry_id,
        entry_type=LedgerEntryType.CORRECTION,
        payload=_payload(record),
        version_stamp=stamp,
    )


def head_hash_to_link(head: StoredLedgerEntry | None) -> str:
    """The hash a new entry links to: the head's own, or the genesis hash on an empty ledger.

    A head that does not match its own hash stops the append (never a default).
    """
    if head is None:
        return GENESIS_HASH
    problem = entry_hash_problem(head)
    if problem is not None or head.entry_hash is None:
        reason = "no hash" if problem is None else problem.detail
        raise LedgerHeadUnverifiableError(f"the latest ledger entry cannot be extended: {reason}")
    return head.entry_hash


class LedgerAppendService(BaseBusinessService):
    """The one writer of ledger entries."""

    @inject
    def __init__(self, postgres_service: PostgresService, repository: LedgerRepository) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._repository = repository

    async def append_decision(
        self, record: DecisionRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record a decision as the next entry."""
        return await self._append(build_decision_draft(record, stamp, uuid4()), None)

    async def append_correction(
        self, record: CorrectionRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record a correction that references an existing entry by its hash."""
        return await self._append(
            build_correction_draft(record, stamp, uuid4()), record.corrects_entry_hash
        )

    async def append_decision_in(
        self, session: AsyncSession, record: DecisionRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record a decision in the caller's transaction; it commits or rolls back with it."""
        return await self._append_in(session, build_decision_draft(record, stamp, uuid4()), None)

    async def append_correction_in(
        self, session: AsyncSession, record: CorrectionRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record a correction in the caller's transaction; it commits or rolls back with it."""
        return await self._append_in(
            session, build_correction_draft(record, stamp, uuid4()), record.corrects_entry_hash
        )

    async def verify(self, anchor: ChainAnchor | None = None) -> ChainVerification:
        """Read the whole chain and check it, against the anchor when one is given."""
        async with self._postgres.get_session() as session:
            entries = await self._repository.read_all(session)
        return verify_chain(entries, anchor)

    async def _append(
        self, draft: LedgerEntryDraft, corrects_entry_hash: str | None
    ) -> StoredLedgerEntry:
        async with self._postgres.transaction() as session:
            return await self._append_in(session, draft, corrects_entry_hash)

    async def _append_in(
        self, session: AsyncSession, draft: LedgerEntryDraft, corrects_entry_hash: str | None
    ) -> StoredLedgerEntry:
        await self._repository.lock_chain(session)
        if corrects_entry_hash is not None:
            original = await self._repository.get_by_hash(session, corrects_entry_hash)
            if original is None:
                raise CorrectedEntryNotFoundError(corrects_entry_hash)
        head = await self._repository.latest(session)
        previous_hash = head_hash_to_link(head)
        if not await self._repository.head_reaches_genesis(session):
            raise LedgerHeadOrphanError()
        sealed = seal_entry(draft, previous_hash)
        return await self._repository.insert(session, sealed)


def _payload(record: DecisionRecord | CorrectionRecord) -> dict[str, JsonValue]:
    return record.model_dump(mode="json")
