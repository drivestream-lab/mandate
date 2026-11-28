"""Delivery retries and a message sent twice has one effect; a repeated inbound event is ignored.

Runs against a real Postgres as the runtime role; see tests/integration/conftest.py. The
downstream is a receiver that applies a message once per idempotency key, as a real receiver
that honours the key does.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from src.business_services.inbound.inbound_event_service import InboundEventService
from src.business_services.outbox.outbox_dispatch_service import (
    OutboxDeliveryError,
    OutboxDispatchService,
)
from src.database.postgres.repository.inbound.inbound_event_repository import (
    InboundEventRepository,
)
from src.database.postgres.repository.outbox.outbox_repository import OutboxRepository
from src.infra_services.postgres_service import PostgresService
from src.models.outbox_models import InboundEvent, NewOutboxMessage, OutboxMessage
from tests.integration.outbox.helpers import ManualClock, count_rows


class _Receiver:
    """Applies each idempotency key once, whatever number of times it is sent."""

    def __init__(self, refuse_first: int = 0, lose_first_reply: bool = False) -> None:
        self.refuse_first = refuse_first
        self.lose_first_reply = lose_first_reply
        self.sends: list[str] = []
        self.effects: dict[str, dict[str, JsonValue]] = {}

    async def deliver(self, message: OutboxMessage) -> None:
        self.sends.append(message.idempotency_key.value)
        if self.refuse_first > 0:
            self.refuse_first -= 1
            raise OutboxDeliveryError("destination unavailable")
        self.effects.setdefault(message.idempotency_key.value, message.payload)
        if self.lose_first_reply:
            self.lose_first_reply = False
            raise OutboxDeliveryError("reply lost after the destination applied the message")


def _message(step: str = "approved") -> NewOutboxMessage:
    return NewOutboxMessage(
        work_item_id="work-item-1", step=step, destination="paperclip", payload={"step": step}
    )


async def _queue(postgres: PostgresService, service: OutboxDispatchService) -> bool:
    async with postgres.transaction() as session:
        return await service.enqueue(session, _message())


@pytest.mark.req("REQ-55")
async def test_the_same_step_queued_twice_is_one_message(postgres: PostgresService) -> None:
    service = OutboxDispatchService(postgres, OutboxRepository(), _Receiver(), ManualClock())
    assert await _queue(postgres, service) is True
    assert await _queue(postgres, service) is False
    assert await count_rows(postgres, "outbox.messages") == 1


@pytest.mark.req("REQ-55")
async def test_a_refused_message_is_retried_later_and_delivered(postgres: PostgresService) -> None:
    receiver, clock = _Receiver(refuse_first=2), ManualClock()
    service = OutboxDispatchService(postgres, OutboxRepository(), receiver, clock)
    await _queue(postgres, service)

    assert (await service.dispatch_due()).failed == 1
    assert (await service.dispatch_due()).failed == 0  # not due yet: nothing is tried
    assert len(receiver.sends) == 1
    clock.advance(timedelta(seconds=6))
    assert (await service.dispatch_due()).failed == 1
    clock.advance(timedelta(seconds=11))
    report = await service.dispatch_due()
    assert (report.delivered, report.failed) == (1, 0)
    assert len(receiver.effects) == 1
    assert await count_rows(postgres, "outbox.messages", "delivered_at IS NOT NULL") == 1
    assert await count_rows(postgres, "outbox.messages", "attempts = 2") == 1
    clock.advance(timedelta(hours=1))
    assert (await service.dispatch_due()).delivered == 0


@pytest.mark.req("REQ-55")
async def test_a_message_sent_twice_has_one_effect(postgres: PostgresService) -> None:
    receiver, clock = _Receiver(lose_first_reply=True), ManualClock()
    service = OutboxDispatchService(postgres, OutboxRepository(), receiver, clock)
    await _queue(postgres, service)

    await service.dispatch_due()  # applied downstream, but the reply was lost
    clock.advance(timedelta(seconds=6))
    await service.dispatch_due()  # sent again
    assert len(receiver.sends) == 2
    assert receiver.sends[0] == receiver.sends[1]
    assert len(receiver.effects) == 1


@pytest.mark.req("REQ-55")
async def test_two_dispatchers_do_not_send_one_message_twice(postgres: PostgresService) -> None:
    receiver = _Receiver()
    clock = ManualClock()
    services = [
        OutboxDispatchService(postgres, OutboxRepository(), receiver, clock) for _ in range(3)
    ]
    await _queue(postgres, services[0])
    await asyncio.gather(*(service.dispatch_due() for service in services))
    assert len(receiver.sends) == 1


def _event(source: str = "github", event_id: str = "evt-1") -> InboundEvent:
    return InboundEvent(source=source, event_id=event_id, payload={"n": 1})


async def _receive(postgres: PostgresService, event: InboundEvent) -> bool:
    service = InboundEventService(InboundEventRepository())
    async with postgres.transaction() as session:
        return await service.record_if_new(session, event)


@pytest.mark.req("REQ-55")
async def test_a_repeated_inbound_event_is_recorded_once_and_ignored_after(
    postgres: PostgresService,
) -> None:
    assert await _receive(postgres, _event()) is True
    assert await _receive(postgres, _event()) is False
    assert await _receive(postgres, _event()) is False
    assert await _receive(postgres, _event(source="paperclip")) is True
    assert await count_rows(postgres, "inbound.events") == 2


@pytest.mark.req("REQ-55")
async def test_events_racing_on_one_id_are_recorded_once(postgres: PostgresService) -> None:
    results = await asyncio.gather(
        *(_receive(postgres, _event("github", "race")) for _ in range(6))
    )
    assert results.count(True) == 1
    assert await count_rows(postgres, "inbound.events", "event_id = 'race'") == 1


@pytest.mark.req("REQ-55")
async def test_an_event_whose_action_failed_is_not_remembered(postgres: PostgresService) -> None:
    service = InboundEventService(InboundEventRepository())
    with pytest.raises(RuntimeError):
        async with postgres.transaction() as session:
            assert await service.record_if_new(session, _event(event_id="retry-me"))
            raise RuntimeError("the action failed")
    assert await _receive(postgres, _event(event_id="retry-me")) is True


@pytest.mark.req("REQ-55")
async def test_the_runtime_role_cannot_edit_or_remove_a_recorded_event(
    postgres: PostgresService,
) -> None:
    await _receive(postgres, _event(event_id=str(uuid.uuid4())))
    for statement in ("UPDATE inbound.events SET source = 'x'", "DELETE FROM inbound.events"):
        async with postgres.transaction() as session:
            with pytest.raises(DBAPIError) as refusal:
                await session.execute(text(statement))
        assert "permission denied" in str(refusal.value)


@pytest.mark.parametrize("offset", [timedelta(days=-400), timedelta(days=400)])
async def test_a_queued_message_is_due_at_the_services_own_clock(
    postgres: PostgresService, offset: timedelta
) -> None:
    receiver, clock = _Receiver(), ManualClock()
    clock.advance(offset)
    service = OutboxDispatchService(postgres, OutboxRepository(), receiver, clock)
    await _queue(postgres, service)

    async with postgres.get_session() as session:
        result = await session.execute(text("SELECT next_attempt_at FROM outbox.messages"))
        assert result.scalar_one() == clock.now()
    report = await service.dispatch_due()
    assert (report.delivered, report.failed) == (1, 0)
