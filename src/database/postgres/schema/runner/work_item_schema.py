"""A unit of work the runner is moving through its steps."""

import uuid

from sqlalchemy import Column, Text, UUID

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel

RUNNER_SCHEMA = "runner"


class WorkItemSchema(PostgresBaseModel):
    """One work item and its current state."""

    __tablename__ = "work_items"
    __table_args__ = {"schema": RUNNER_SCHEMA}

    work_item_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    state = Column(Text, nullable=False)
