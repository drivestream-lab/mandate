"""Queues outbox messages in the caller's transaction, then delivers them and retries failures.

Queue. A state change, its ledger entry and its outbox message are written in one transaction
by the caller, so they all exist or none does. A message carries an idempotency key derived
from its work item and step; queueing the same pair again adds nothing.

Deliver. Each pass takes due messages one at a time, each in its own transaction: lock the row
(a second dispatcher skips it), hand it to the transport, then record the delivery. A failed
delivery is counted and tried again later, with a wait that grows. A crash between the
transport accepting a message and the delivery being recorded sends it again, so delivery is
at least once; the key goes with every send, and a receiver that honours it applies the
message once.
"""

from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.business_services.base_business_service import BaseBusinessService
from src.database.postgres.repository.outbox.outbox_repository import OutboxRepository
from src.engine.kernel.clock import Clock, utc_now
from src.engine.kernel.idempotency_key import derive_idempotency_key
from src.engine.outbox.retry_schedule import retry_delay
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.postgres_service import PostgresService
from src.models.outbox_models import NewOutboxMessage, OutboxDispatchReport, OutboxMessage


class OutboxDeliveryError(BaseAppException):
    """A transport could not deliver a message; the dispatcher keeps it and tries again."""

    def __init__(self, detail: str) -> None:
        super().__init__(code="OUTBOX_DELIVERY_FAILED", message=detail, status_code=502)


class OutboxTransport(Protocol):
    """Sends one message to its destination, with the message's idempotency key."""

    async def deliver(self, message: OutboxMessage) -> None:
        """Send the message; raise OutboxDeliveryError when it was not accepted."""
        ...


class OutboxDispatchService(BaseBusinessService):
    """Queues and delivers outbox messages."""

    def __init__(
        self,
        postgres_service: PostgresService,
        repository: OutboxRepository,
        transport: OutboxTransport,
        clock: Clock,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._repository = repository
        self._transport = transport
        self._clock = clock

    async def enqueue(self, session: AsyncSession, message: NewOutboxMessage) -> bool:
        """Queue a message in the caller's transaction; False when the same step was queued."""
        key = derive_idempotency_key(
            message.work_item_id, f"outbox:{message.destination}:{message.step}"
        )
        return await self._repository.enqueue(session, message, key, utc_now(self._clock))

    async def dispatch_due(self, limit: int = 100) -> OutboxDispatchReport:
        """Deliver every due message, up to the limit, and schedule the failures for a retry."""
        now = utc_now(self._clock)
        delivered = failed = 0
        for _ in range(limit):
            outcome = await self._dispatch_next(now)
            if outcome is None:
                break
            if outcome:
                delivered += 1
            else:
                failed += 1
        return OutboxDispatchReport(delivered=delivered, failed=failed)

    async def _dispatch_next(self, now: datetime) -> bool | None:
        """Handle one due message: True delivered, False failed, None when none was due."""
        async with self._postgres.transaction() as session:
            message = await self._repository.claim_next_due(session, now)
            if message is None:
                return None
            try:
                await self._transport.deliver(message)
            except OutboxDeliveryError as error:
                delay = retry_delay(message.attempts + 1)
                await self._repository.record_failure(
                    session, message, error.message, now + delay, now
                )
                return False
            await self._repository.mark_delivered(session, message, now)
            return True
