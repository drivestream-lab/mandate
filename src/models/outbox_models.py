"""Outbox and inbound models: a message waiting for delivery and an event received once."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.models.kernel_models import IdempotencyKey

_NON_BLANK = r"\S"


class NewOutboxMessage(BaseModel):
    """A message to send once the unit of work that produced it commits.

    The work item and step identify the effect: the same pair enqueued twice is one message.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    work_item_id: str = Field(min_length=1, pattern=_NON_BLANK, description="Work item id")
    step: str = Field(
        min_length=1, pattern=_NON_BLANK, description="Step that produced the message"
    )
    destination: str = Field(min_length=1, pattern=_NON_BLANK, description="Where it is delivered")
    payload: dict[str, JsonValue] = Field(description="The message body")


class OutboxMessage(BaseModel):
    """A stored message, as the dispatcher reads it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    destination: str
    payload: dict[str, JsonValue]
    idempotency_key: IdempotencyKey
    attempts: int = Field(ge=0, description="Deliveries tried and failed so far")
    next_attempt_at: datetime
    last_error: str | None
    delivered_at: datetime | None


class OutboxDispatchReport(BaseModel):
    """What one dispatch pass did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delivered: int = Field(ge=0)
    failed: int = Field(ge=0)


class InboundEvent(BaseModel):
    """An event received from outside, identified by its source and the id the source gave it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, pattern=_NON_BLANK, description="Who sent the event")
    event_id: str = Field(min_length=1, pattern=_NON_BLANK, description="The sender's event id")
    payload: dict[str, JsonValue] = Field(description="The event body")
