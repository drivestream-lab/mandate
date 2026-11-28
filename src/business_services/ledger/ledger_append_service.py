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
    CallRevealRecord,
    CorrectionRecord,
    DecisionRecord,
    LedgerEntryDraft,
    LedgerEntryType,
    SealedCallRecord,
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

    async def append_sealed_call_in(
        self, session: AsyncSession, record: SealedCallRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record a sealed call in the caller's transaction; it commits or rolls back with it.

        A LedgerHeadOrphanError leaves the caller's transaction to roll back: never commit it.
        """
        draft = LedgerEntryDraft(
            entry_id=uuid4(),
            entry_type=LedgerEntryType.SEALED_CALL,
            payload=record.model_dump(mode="json"),
            version_stamp=stamp,
        )
        return await self._append_in(session, draft, None)

    async def append_call_reveal_in(
        self, session: AsyncSession, record: CallRevealRecord, stamp: VersionStamp
    ) -> StoredLedgerEntry:
        """Record the reveal of a sealed call in the caller's transaction."""
        draft = LedgerEntryDraft(
            entry_id=uuid4(),
            entry_type=LedgerEntryType.CALL_REVEAL,
            payload=record.model_dump(mode="json"),
            version_stamp=stamp,
        )
        return await self._append_in(session, draft, None)

    async def record_decision_once(
        self, record: DecisionRecord, stamp: VersionStamp, change_reason: str
    ) -> StoredLedgerEntry | None:
        """Record a decision unless the same holder's latest word on this role and version already
        says the same; a changed choice is recorded as a correction naming the earlier entry.

        The look-up and the write share one transaction under the chain lock, so two callers
        racing on one decision write it once. Returns None when nothing was written.
        """
        async with self._postgres.transaction() as session:
            await self._repository.lock_chain(session)
            existing = await self._repository.find_latest_decision(
                session, record.actor, record.role, record.target_version
            )
            if existing is None:
                return await self._append_in(
                    session, build_decision_draft(record, stamp, uuid4()), None
                )
            if _choice_of(existing) == record.choice:
                return None
            if existing.entry_hash is None:
                raise LedgerHeadUnverifiableError("the earlier decision has no hash")
            correction = CorrectionRecord(
                corrects_entry_hash=existing.entry_hash,
                actor=record.actor,
                reason=change_reason,
                corrected_decision=record,
            )
            return await self._append_in(
                session,
                build_correction_draft(correction, stamp, uuid4()),
                correction.corrects_entry_hash,
            )

    async def latest_choice(self, actor: str, role: str, target_version: str) -> str | None:
        """The choice the holder last recorded on this role and version, or None."""
        async with self._postgres.get_session() as session:
            existing = await self._repository.find_latest_decision(
                session, actor, role, target_version
            )
        return None if existing is None else _choice_of(existing)

    async def latest_decision_record(
        self, actor: str, role: str, target_version: str
    ) -> DecisionRecord | None:
        """What the holder last recorded on this role and version, or None."""
        async with self._postgres.get_session() as session:
            existing = await self._repository.find_latest_decision(
                session, actor, role, target_version
            )
        return None if existing is None else _record_of(existing)

    async def latest_choice_for_role(self, role: str, target_version: str) -> str | None:
        """The choice last recorded on this role and version by anyone, or None."""
        async with self._postgres.get_session() as session:
            existing = await self._repository.find_latest_decision_for_role(
                session, role, target_version
            )
        return None if existing is None else _choice_of(existing)

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


def _record_of(entry: StoredLedgerEntry) -> DecisionRecord:
    """The decision an entry records, or the decision a correction puts in its place."""
    if entry.entry_type == LedgerEntryType.CORRECTION:
        return CorrectionRecord.model_validate(entry.payload).corrected_decision
    return DecisionRecord.model_validate(entry.payload)


def _choice_of(entry: StoredLedgerEntry) -> str:
    """The choice a decision entry, or a correction of one, records."""
    return _record_of(entry).choice


def _payload(record: DecisionRecord | CorrectionRecord) -> dict[str, JsonValue]:
    return record.model_dump(mode="json")
