"""Records inbound events. Every method runs in the caller's transaction."""

from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.postgres.schema.inbound.inbound_event_schema import InboundEventSchema
from src.models.outbox_models import InboundEvent

_EVENTS = InboundEventSchema.__table__


class InboundEventRepository:
    """Data access for inbound.events."""

    async def record_once(self, session: AsyncSession, event: InboundEvent) -> bool:
        """Store the event; False when its source and event id were recorded before.

        The unique constraint decides, so two receivers racing on one event id cannot both win.
        """
        result = await session.execute(
            postgres_insert(_EVENTS)
            .values(source=event.source, event_id=event.event_id, payload=event.payload)
            .on_conflict_do_nothing(index_elements=["source", "event_id"])
            .returning(_EVENTS.c.id)
        )
        return result.first() is not None
