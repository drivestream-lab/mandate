"""A gate a work item must pass before it moves on."""

from sqlalchemy import Column, Text, UUID

from src.database.postgres.schema.base_postgres_schema import PostgresBaseModel

GATES_SCHEMA = "gates"


class GateSchema(PostgresBaseModel):
    """One gate on one work item and its verdict."""

    __tablename__ = "gates"
    __table_args__ = {"schema": GATES_SCHEMA}

    work_item_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    gate_type = Column(Text, nullable=False)
    verdict = Column(Text, nullable=False)
