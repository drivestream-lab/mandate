"""A message committed with the decision that produced it, delivered afterwards."""

from sqlalchemy import Column, Index, Integer, Text, TIMESTAMP, text
from sqlalchemy.dialects.postgresql import JSONB

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel

OUTBOX_SCHEMA = "outbox"


class OutboxMessageSchema(PostgresBaseModel):
    """One message waiting for delivery."""

    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "messages_pending_key",
            "next_attempt_at",
            postgresql_where=text("delivered_at IS NULL"),
        ),
        {"schema": OUTBOX_SCHEMA},
    )

    destination = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    idempotency_key = Column(Text, nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    next_attempt_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    last_error = Column(Text, nullable=True)
    delivered_at = Column(TIMESTAMP(timezone=True), nullable=True)
