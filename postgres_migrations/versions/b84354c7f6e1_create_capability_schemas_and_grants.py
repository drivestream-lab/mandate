"""create capability schemas and grants

One Postgres schema per capability, tables owned by mandate_owner, the runtime role
mandate_app limited to SELECT and a column-limited INSERT on ledger.entries, and a trigger that refuses
UPDATE, DELETE and TRUNCATE on ledger.entries for every role.

Roles. The lab (dev-infra-lab) and the deploy stack (docker/postgres) create the two login
roles with their own passwords; this migration never sets or reads a password. If a role is
missing it is created without LOGIN, so the grants below always have a target. Roles that
already exist are left as they are.

Rewrite mark. The trigger lets a statement through only when its own transaction has a row
in ledger.rewrite_permits for txid_current(). That table is owned by mandate_owner and
granted to no one else, so mandate_app and ordinary sessions cannot write it. The row is
only visible inside the transaction that wrote it, and it is keyed to that transaction, so it
cannot be reused. A later migration that must correct ledger rows inserts its own mark first
and deletes it before it ends:

    INSERT INTO ledger.rewrite_permits (transaction_id, reason)
    VALUES (txid_current(), 'why this migration rewrites the ledger');

A session setting, a role attribute or application_name cannot stand in for the mark. A
BEFORE INSERT OR UPDATE trigger on the table accepts only a permit for txid_current(), so a
permit cannot be planted for another transaction.

What this does not stop. mandate_owner owns the table, and a table owner can always change the
protection itself with its own DDL: ALTER TABLE ... DISABLE TRIGGER, DROP TRIGGER, replacing
the trigger function, ALTER COLUMN ... TYPE ... USING (which rewrites rows without firing row
triggers) and DROP TABLE. A superuser can also set session_replication_role. This is inherent
in ADR-020's model, where mandate_owner owns every object, and no trigger can prevent it. The
protection is that only the migration script uses mandate_owner, and that the hash chain and
checkpoint (the ledger's hash chain task) detect any rewrite that does happen. mandate_app,
the runtime role, has none of these abilities and cannot choose an entry's sequence or time.

Revision ID: b84354c7f6e1
Revises: 
Create Date: 2026-11-27 13:32:00.101818

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

PERMIT_COMMENT = (
    "A row for txid_current() lets a migration rewrite ledger.entries in that transaction. "
    "Only the owner role can write it."
)
OWNER_ROLE = "mandate_owner"
APP_ROLE = "mandate_app"

CAPABILITY_SCHEMAS = (
    "ledger",
    "runner",
    "gates",
    "release",
    "programmes",
    "policy",
    "outbox",
    "inbound",
)
# Every schema but the ledger gives the runtime role full read and write on its tables.
WRITABLE_SCHEMAS = tuple(name for name in CAPABILITY_SCHEMAS if name != "ledger")

# revision identifiers, used by Alembic.
revision: str = 'b84354c7f6e1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    for role in (OWNER_ROLE, APP_ROLE):
        op.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
            f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
        )
    for schema in CAPABILITY_SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        op.execute(f"ALTER SCHEMA {schema} OWNER TO {OWNER_ROLE}")
        op.execute(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC")
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}")

    op.create_table('gates',
    sa.Column('work_item_id', sa.UUID(), nullable=False),
    sa.Column('gate_type', sa.Text(), nullable=False),
    sa.Column('verdict', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False, comment='Unique identifier for the record'),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='Timestamp (UTC) when record was created'),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='Timestamp (UTC) when record was last updated'),
    sa.PrimaryKeyConstraint('id'),
    schema='gates'
    )
    op.create_index(op.f('ix_gates_gates_work_item_id'), 'gates', ['work_item_id'], unique=False, schema='gates')
    op.create_table('entries',
    sa.Column('sequence', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('entry_id', sa.UUID(), nullable=False),
    sa.Column('entry_type', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('previous_hash', sa.Text(), nullable=True),
    sa.Column('entry_hash', sa.Text(), nullable=True),
    sa.Column('recorded_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('sequence'),
    sa.UniqueConstraint('entry_id'),
    schema='ledger'
    )
    op.create_table('messages',
    sa.Column('destination', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('delivered_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False, comment='Unique identifier for the record'),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='Timestamp (UTC) when record was created'),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='Timestamp (UTC) when record was last updated'),
    sa.PrimaryKeyConstraint('id'),
    schema='outbox'
    )
    op.create_table('work_items',
    sa.Column('work_item_id', sa.UUID(), nullable=False),
    sa.Column('state', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False, comment='Unique identifier for the record'),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='Timestamp (UTC) when record was created'),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='Timestamp (UTC) when record was last updated'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('work_item_id'),
    schema='runner'
    )

    op.create_table(
        "rewrite_permits",
        sa.Column("transaction_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("marked_by", sa.Text(), server_default=sa.text("CURRENT_USER"), nullable=False),
        sa.Column(
            "marked_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("length(reason) > 0", name="rewrite_permits_reason_not_empty"),
        sa.PrimaryKeyConstraint("transaction_id"),
        comment=PERMIT_COMMENT,
        schema="ledger",
    )
    op.execute(
        """
        CREATE FUNCTION ledger.reject_entry_rewrite() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $fn$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ledger.rewrite_permits WHERE transaction_id = txid_current()
            ) THEN
                IF TG_OP = 'UPDATE' THEN
                    RETURN NEW;
                END IF;
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'ledger.entries is append-only: % is refused', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END
        $fn$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ledger.reject_entry_rewrite() FROM PUBLIC")
    # A permit only counts for the transaction that writes it, so it cannot be planted ahead.
    op.execute(
        """
        CREATE FUNCTION ledger.require_own_transaction() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $fn$
        BEGIN
            IF NEW.transaction_id IS DISTINCT FROM txid_current() THEN
                RAISE EXCEPTION 'a rewrite permit is only valid for the current transaction'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION ledger.require_own_transaction() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER rewrite_permits_own_transaction BEFORE INSERT OR UPDATE "
        "ON ledger.rewrite_permits FOR EACH ROW EXECUTE FUNCTION ledger.require_own_transaction()"
    )
    op.execute(
        "CREATE TRIGGER entries_reject_rewrite BEFORE UPDATE OR DELETE ON ledger.entries "
        "FOR EACH ROW EXECUTE FUNCTION ledger.reject_entry_rewrite()"
    )
    op.execute(
        "CREATE TRIGGER entries_reject_truncate BEFORE TRUNCATE ON ledger.entries "
        "FOR EACH STATEMENT EXECUTE FUNCTION ledger.reject_entry_rewrite()"
    )

    # Ownership: the migration may run as mandate_owner (lab) or as a superuser (deploy stack).
    op.execute(f"ALTER TABLE ledger.entries OWNER TO {OWNER_ROLE}")
    op.execute(f"ALTER TABLE ledger.rewrite_permits OWNER TO {OWNER_ROLE}")
    op.execute(f"ALTER FUNCTION ledger.reject_entry_rewrite() OWNER TO {OWNER_ROLE}")
    op.execute(f"ALTER FUNCTION ledger.require_own_transaction() OWNER TO {OWNER_ROLE}")
    for schema, table in (
        ("runner", "work_items"),
        ("gates", "gates"),
        ("outbox", "messages"),
    ):
        op.execute(f"ALTER TABLE {schema}.{table} OWNER TO {OWNER_ROLE}")

    # Grants: the runtime role appends to and reads the ledger, nothing more.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA ledger FROM {APP_ROLE}")
    # INSERT by column: the sequence and recorded_at stay server-assigned, so the runtime role
    # cannot backdate an entry or pick its place in the chain (OVERRIDING SYSTEM VALUE needs
    # INSERT on the sequence column).
    op.execute(f"GRANT SELECT ON ledger.entries TO {APP_ROLE}")
    op.execute(
        f"GRANT INSERT (entry_id, entry_type, payload, previous_hash, entry_hash) "
        f"ON ledger.entries TO {APP_ROLE}"
    )
    for schema in WRITABLE_SCHEMAS:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} "
            f"TO {APP_ROLE}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {OWNER_ROLE} IN SCHEMA {schema} "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
        )


def downgrade() -> None:
    """Downgrade schema. Refuses while the ledger holds entries."""
    # Lock first, so an insert cannot land between the check and the drop.
    op.execute("LOCK TABLE ledger.entries IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM ledger.entries) THEN "
        "RAISE EXCEPTION 'refusing to drop a ledger that holds entries'; END IF; END $$"
    )
    op.drop_table('work_items', schema='runner')
    op.drop_table('messages', schema='outbox')
    op.drop_table('entries', schema='ledger')
    op.drop_table('rewrite_permits', schema='ledger')
    op.execute("DROP FUNCTION ledger.reject_entry_rewrite()")
    op.execute("DROP FUNCTION ledger.require_own_transaction()")
    op.drop_index(op.f('ix_gates_gates_work_item_id'), table_name='gates', schema='gates')
    op.drop_table('gates', schema='gates')
    for schema in reversed(CAPABILITY_SCHEMAS):
        op.execute(f"DROP SCHEMA {schema}")
