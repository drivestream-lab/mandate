"""The mark a migration sets to rewrite the ledger inside its own transaction.

Owned by the owner role and granted to no one else; the runtime role cannot read or write it.
A trigger accepts only a permit for the current transaction id, and the migration deletes its
permit before it ends. This model exists so that migration autogenerate keeps the table.
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, Text, TIMESTAMP, text

from src.database.postgres.schema.base_postgres_schema import BasePostgres
from src.database.postgres.schema.ledger.ledger_entry_schema import LEDGER_SCHEMA


class RewritePermitSchema(BasePostgres):
    """A permit for one transaction to rewrite ledger.entries."""

    __tablename__ = "rewrite_permits"
    __table_args__ = (
        CheckConstraint("length(reason) > 0", name="rewrite_permits_reason_not_empty"),
        {
            "schema": LEDGER_SCHEMA,
            "comment": (
                "A row for txid_current() lets a migration rewrite ledger.entries in that "
                "transaction. Only the owner role can write it."
            ),
        },
    )

    transaction_id = Column(BigInteger, primary_key=True, autoincrement=False)
    reason = Column(Text, nullable=False)
    marked_by = Column(Text, nullable=False, server_default=text("CURRENT_USER"))
    marked_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
