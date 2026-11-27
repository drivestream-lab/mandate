"""The ledger's one table. Append-only: the runtime role may only insert and select.

The database refuses UPDATE, DELETE and TRUNCATE here for every role except inside a
migration that marks its own transaction for it (ledger.rewrite_permits). mandate_app may
only select, and insert the columns it supplies; the sequence and recorded_at are assigned by
the database.

The owner role is not stopped by this. mandate_owner owns the table, so it can disable or
drop the trigger, replace its function, rewrite a column with ALTER COLUMN ... USING, or drop
the table; a superuser can also use session_replication_role. That is inherent in ADR-020's
ownership model. mandate_owner is used only by the migration script, and the hash chain over
these rows is what detects a rewrite that does happen.
"""

import uuid

from sqlalchemy import BigInteger, Column, Identity, Text, TIMESTAMP, UUID, func
from sqlalchemy.dialects.postgresql import JSONB

from src.database.postgres.schema.base_postgres_schema import BasePostgres

LEDGER_SCHEMA = "ledger"


class LedgerEntrySchema(BasePostgres):
    """One signed fact in the ledger."""

    __tablename__ = "entries"
    __table_args__ = {"schema": LEDGER_SCHEMA}

    sequence = Column(BigInteger, Identity(always=True), primary_key=True)
    entry_id = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    entry_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    previous_hash = Column(Text, nullable=True)
    entry_hash = Column(Text, nullable=True)
    recorded_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
