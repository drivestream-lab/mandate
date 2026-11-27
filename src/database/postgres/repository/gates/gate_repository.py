"""Writes a gate's state row."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.postgres.schema.gates.gate_schema import GateSchema


class GateRepository:
    """Data access for gates.gates; every method runs in the caller's transaction."""

    async def open_gate(self, session: AsyncSession, work_item_id: UUID, gate_type: str) -> UUID:
        """Insert a gate with the verdict `open`; return its id."""
        gate_id = uuid4()
        session.add(
            GateSchema(id=gate_id, work_item_id=work_item_id, gate_type=gate_type, verdict="open")
        )
        await session.flush()
        return gate_id
