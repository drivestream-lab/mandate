"""outbox delivery state and inbound events

Outbox messages gain an idempotency key (unique), an attempt count, the time of the next attempt
and the last error. inbound.events keeps one row per source and event id. The runtime role keeps
its existing rights on outbox.messages, which cover queueing and delivery, and gets select and
insert only on inbound.events. outbox.messages must hold no rows when this runs (nothing wrote
to it before).

Revision ID: 124cdf11d411
Revises: f23d8a4e2b93
Create Date: 2026-11-27 15:05:38.392801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '124cdf11d411'
down_revision: Union[str, Sequence[str], None] = 'f23d8a4e2b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('events',
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('event_id', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False, comment='Unique identifier for the record'),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='Timestamp (UTC) when record was created'),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='Timestamp (UTC) when record was last updated'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'event_id', name='events_source_event_id_key'),
    schema='inbound'
    )
    op.add_column('messages', sa.Column('idempotency_key', sa.Text(), nullable=False), schema='outbox')
    op.add_column('messages', sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False), schema='outbox')
    op.add_column('messages', sa.Column('next_attempt_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False), schema='outbox')
    op.add_column('messages', sa.Column('last_error', sa.Text(), nullable=True), schema='outbox')
    op.create_index('messages_pending_key', 'messages', ['next_attempt_at'], unique=False, schema='outbox', postgresql_where=sa.text('delivered_at IS NULL'))
    op.create_unique_constraint('messages_idempotency_key_key', 'messages', ['idempotency_key'], schema='outbox')

    # inbound.events is created by whoever runs the migration, so name its owner and the runtime
    # role's rights here: it records an event and reads it back, and never edits or removes one.
    op.execute("ALTER TABLE inbound.events OWNER TO mandate_owner")
    op.execute("REVOKE ALL ON inbound.events FROM mandate_app")
    op.execute("GRANT SELECT, INSERT ON inbound.events TO mandate_app")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('messages_idempotency_key_key', 'messages', schema='outbox', type_='unique')
    op.drop_index('messages_pending_key', table_name='messages', schema='outbox', postgresql_where=sa.text('delivered_at IS NULL'))
    op.drop_column('messages', 'last_error', schema='outbox')
    op.drop_column('messages', 'next_attempt_at', schema='outbox')
    op.drop_column('messages', 'attempts', schema='outbox')
    op.drop_column('messages', 'idempotency_key', schema='outbox')
    op.drop_table('events', schema='inbound')
