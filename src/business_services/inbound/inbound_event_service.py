"""Receives inbound events once: a repeated event id is recorded the first time and ignored after."""

from injector import inject
from sqlalchemy.ext.asyncio import AsyncSession

from src.business_services.base_business_service import BaseBusinessService
from src.database.postgres.repository.inbound.inbound_event_repository import (
    InboundEventRepository,
)
from src.models.outbox_models import InboundEvent


class InboundEventService(BaseBusinessService):
    """Decides whether an inbound event is new."""

    @inject
    def __init__(self, repository: InboundEventRepository) -> None:
        super().__init__()
        self._repository = repository

    async def record_if_new(self, session: AsyncSession, event: InboundEvent) -> bool:
        """True when this is the first time the event was seen, so the caller acts on it.

        Runs in the caller's transaction: record the event and act on it together, so a failure
        in the action also forgets the event and the sender's retry is not ignored.
        """
        return await self._repository.record_once(session, event)
