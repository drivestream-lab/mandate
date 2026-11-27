"""A message committed with the decision that produced it, delivered afterwards."""

from sqlalchemy import Column, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel

OUTBOX_SCHEMA = "outbox"


class OutboxMessageSchema(PostgresBaseModel):
    """One message waiting for delivery."""

    __tablename__ = "messages"
    __table_args__ = {"schema": OUTBOX_SCHEMA}

    destination = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    delivered_at = Column(TIMESTAMP(timezone=True), nullable=True)
