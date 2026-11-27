"""Reads and appends ledger entries. The only code that touches ledger.entries.

Append only: there is no update or delete here, and the runtime role could not run one. The
repository does not decide what an entry is or how it is hashed; the append service does that
with the engine. This class is standalone because ledger.entries has no id, created_at or
updated_at column, so the generic base repository does not fit.

The payload column holds the entry's content together with its version stamp, so a stamp is
kept with every entry without a column that the runtime role would need more rights to fill.
A row written outside the writer has no such envelope; it reads back with no stamp, and
verification reports it.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.postgres.schema.ledger.ledger_entry_schema import LedgerEntrySchema
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import (
    LedgerPayloadEnvelope,
    SealedLedgerEntry,
    StoredLedgerEntry,
)

CHAIN_LOCK_KEY = 7_340_021_118_553_947
"""Advisory lock key that serialises appends. Any role may take it; it is released at commit."""

_ENTRIES = LedgerEntrySchema.__table__
_ENVELOPE_KEYS = frozenset({"content", "version_stamp"})


class LedgerRepository:
    """Data access for ledger.entries; every method runs in the caller's transaction."""

    async def lock_chain(self, session: AsyncSession) -> None:
        """Wait for, then hold until the transaction ends, the right to extend the chain."""
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CHAIN_LOCK_KEY})

    async def latest(self, session: AsyncSession) -> StoredLedgerEntry | None:
        """The entry with the highest sequence, or None when the ledger is empty."""
        result = await session.execute(
            select(_ENTRIES).order_by(_ENTRIES.c.sequence.desc()).limit(1)
        )
        row = result.first()
        return None if row is None else _to_stored(row)

    async def get_by_hash(self, session: AsyncSession, entry_hash: str) -> StoredLedgerEntry | None:
        """The entry with this hash, or None."""
        result = await session.execute(select(_ENTRIES).where(_ENTRIES.c.entry_hash == entry_hash))
        row = result.first()
        return None if row is None else _to_stored(row)

    async def read_all(self, session: AsyncSession) -> list[StoredLedgerEntry]:
        """Every entry in sequence order."""
        result = await session.execute(select(_ENTRIES).order_by(_ENTRIES.c.sequence))
        return [_to_stored(row) for row in result.all()]

    async def insert(self, session: AsyncSession, entry: SealedLedgerEntry) -> StoredLedgerEntry:
        """Write one sealed entry; the database assigns its sequence and recorded_at."""
        envelope = LedgerPayloadEnvelope(content=entry.payload, version_stamp=entry.version_stamp)
        result = await session.execute(
            insert(_ENTRIES)
            .values(
                entry_id=entry.entry_id,
                entry_type=entry.entry_type,
                payload=envelope.model_dump(mode="json"),
                previous_hash=entry.previous_hash,
                entry_hash=entry.entry_hash,
            )
            .returning(_ENTRIES.c.sequence, _ENTRIES.c.recorded_at)
        )
        written = result.one()
        return StoredLedgerEntry(
            sequence=written.sequence,
            entry_id=entry.entry_id,
            entry_type=entry.entry_type,
            payload=entry.payload,
            version_stamp=entry.version_stamp,
            previous_hash=entry.previous_hash,
            entry_hash=entry.entry_hash,
            recorded_at=written.recorded_at,
        )


class _LedgerRow(BaseModel):
    """The columns of one ledger.entries row, as read."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    sequence: int
    entry_id: UUID
    entry_type: str
    payload: dict[str, JsonValue]
    previous_hash: str | None
    entry_hash: str | None
    recorded_at: datetime


def _to_stored(row: object) -> StoredLedgerEntry:
    """Map a ledger.entries row to a model, splitting the payload envelope when it is there."""
    values = _LedgerRow.model_validate(row, from_attributes=True)
    content, stamp = _split_envelope(values.payload)
    return StoredLedgerEntry(
        sequence=values.sequence,
        entry_id=values.entry_id,
        entry_type=values.entry_type,
        payload=content,
        version_stamp=stamp,
        previous_hash=values.previous_hash,
        entry_hash=values.entry_hash,
        recorded_at=values.recorded_at,
    )


def _split_envelope(
    payload: dict[str, JsonValue],
) -> tuple[dict[str, JsonValue], VersionStamp | None]:
    """Return the content and stamp; a payload that is not an envelope has no stamp."""
    if frozenset(payload) != _ENVELOPE_KEYS:
        return payload, None
    try:
        envelope = LedgerPayloadEnvelope.model_validate(payload)
    except ValidationError:
        return payload, None
    return envelope.content, envelope.version_stamp
