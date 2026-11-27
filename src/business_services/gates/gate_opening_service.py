"""Opens a gate: gets the deciding role's call, seals it with the gate state, then posts the brief.

Order matters. The call is hashed into the ledger and committed together with the gate row
before anything is posted, so the pull request never shows a gate whose call is not sealed.
A sealing failure (an orphan ledger head included) rolls the transaction back and nothing is
posted. The brief is rendered from the gate's content; at intent and design gates the call
is not an input to the text at all.
"""

from typing import Protocol
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.sealed_call_service import (
    DecidingRoleCallSource,
    SealedCallService,
)
from src.database.postgres.repository.gates.gate_repository import GateRepository
from src.engine.gates.brief import render_brief
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import GateBrief, OpenedGate, PullRequestRef
from src.models.kernel_models import VersionStamp


class BriefPoster(Protocol):
    """Posts a brief on a gate's pull request."""

    async def post_brief(self, pull_request: PullRequestRef, body: str) -> None: ...


class GateOpeningService(BaseBusinessService):
    """Opens gates with a sealed call and a posted brief."""

    @inject
    def __init__(
        self,
        postgres_service: PostgresService,
        gates: GateRepository,
        sealed_calls: SealedCallService,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._gates = gates
        self._sealed_calls = sealed_calls

    async def open_gate(
        self,
        work_item_id: UUID,
        brief: GateBrief,
        pull_request: PullRequestRef,
        source: DecidingRoleCallSource,
        poster: BriefPoster,
        stamp: VersionStamp,
    ) -> OpenedGate:
        """Seal the call (or its absence) with the gate row, commit, then post the brief."""
        call = await self._sealed_calls.obtain_call(source, brief)
        async with self._postgres.transaction() as session:
            gate_id = await self._gates.open_gate(session, work_item_id, brief.gate_class.value)
            sealed = await self._sealed_calls.seal_in(session, gate_id, brief.head_sha, call, stamp)
        body = render_brief(brief, call)
        await poster.post_brief(pull_request, body)
        return OpenedGate(gate_id=gate_id, sealed=sealed, brief_body=body)
