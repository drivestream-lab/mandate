"""An event received from outside, kept once per source and event id."""

from sqlalchemy import Column, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel

INBOUND_SCHEMA = "inbound"


class InboundEventSchema(PostgresBaseModel):
    """One received event."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("source", "event_id", name="events_source_event_id_key"),
        {"schema": INBOUND_SCHEMA},
    )

    source = Column(Text, nullable=False)
    event_id = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
