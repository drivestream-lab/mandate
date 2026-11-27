"""Reads and writes outbox.messages. Every method runs in the caller's transaction."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.postgres.schema.outbox.outbox_message_schema import OutboxMessageSchema
from src.models.kernel_models import IdempotencyKey
from src.models.outbox_models import NewOutboxMessage, OutboxMessage

_MESSAGES = OutboxMessageSchema.__table__


class OutboxRepository:
    """Data access for outbox.messages."""

    async def enqueue(
        self, session: AsyncSession, message: NewOutboxMessage, key: IdempotencyKey
    ) -> bool:
        """Add a message; False when one with the same key is already there (nothing changes)."""
        result = await session.execute(
            postgres_insert(_MESSAGES)
            .values(
                destination=message.destination,
                payload=message.payload,
                idempotency_key=key.value,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(_MESSAGES.c.id)
        )
        return result.first() is not None

    async def claim_next_due(self, session: AsyncSession, now: datetime) -> OutboxMessage | None:
        """Lock the oldest undelivered message that is due; others skip a locked row."""
        result = await session.execute(
            select(_MESSAGES)
            .where(_MESSAGES.c.delivered_at.is_(None), _MESSAGES.c.next_attempt_at <= now)
            .order_by(_MESSAGES.c.next_attempt_at, _MESSAGES.c.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = result.first()
        if row is None:
            return None
        return OutboxMessage(
            id=row.id,
            destination=row.destination,
            payload=row.payload,
            idempotency_key=IdempotencyKey(value=row.idempotency_key),
            attempts=row.attempts,
            next_attempt_at=row.next_attempt_at,
            last_error=row.last_error,
            delivered_at=row.delivered_at,
        )

    async def mark_delivered(
        self, session: AsyncSession, message: OutboxMessage, now: datetime
    ) -> None:
        """Record that the message was delivered."""
        await session.execute(
            update(_MESSAGES)
            .where(_MESSAGES.c.id == message.id)
            .values(delivered_at=now, last_error=None, updated_at=now)
        )

    async def record_failure(
        self,
        session: AsyncSession,
        message: OutboxMessage,
        error: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> None:
        """Count a failed delivery and say when to try again."""
        await session.execute(
            update(_MESSAGES)
            .where(_MESSAGES.c.id == message.id)
            .values(
                attempts=message.attempts + 1,
                last_error=error,
                next_attempt_at=next_attempt_at,
                updated_at=now,
            )
        )
