"""Shared pieces of the sign-a-gate journeys: the services wired as the container wires them."""

import uuid

from src.business_services.gates.gate_decision_check_service import GateDecisionCheckService
from src.business_services.gates.gate_opening_service import GateOpeningService
from src.business_services.gates.non_merge_decision_service import NonMergeDecisionService
from src.business_services.gates.sealed_call_service import SealedCallService
from src.business_services.gates.signoff_service import SignoffService
from src.business_services.gates.signoff_voiding_service import SignoffVoidingService
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.database.postgres.repository.gates.gate_repository import GateRepository
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import BriefOption, GateBrief, GateClassType, RoleBrief
from src.models.kernel_models import NamedVersion, VersionStamp
from src.models.ledger_models import EvidenceReference
from tests.journeys.test_agents.conftest import AgentDesk

STAMP = VersionStamp(
    contract="1",
    block_versions=(NamedVersion(name="gate", version="1"),),
    skills=(NamedVersion(name="brief", version="1"),),
    rules="r1",
    agent_setup="a1",
    policy_revision="p1",
    mandate_release="0.1.0",
)


class Services:
    """The gate services over one database."""

    def __init__(self, postgres: PostgresService) -> None:
        repository = LedgerRepository()
        ledger = LedgerAppendService(postgres, repository)
        sealed = SealedCallService(postgres, ledger, repository)
        opening = GateOpeningService(postgres, GateRepository(), sealed)
        self.signoffs = SignoffService(ledger)
        self.check = GateDecisionCheckService(self.signoffs, SignoffVoidingService(ledger))
        self.non_merge = NonMergeDecisionService(
            postgres, GateRepository(), sealed, opening, ledger
        )
        self.ledger = ledger
        self.repository = repository
        self.postgres = postgres

    async def signoffs_recorded(self, gate_label: str) -> int:
        """How many signoff decisions the ledger holds for this gate (not its other records)."""
        async with self.postgres.get_session() as session:
            entries = await self.repository.read_all(session)
        return len(
            [
                e
                for e in entries
                if e.entry_type == "decision" and e.payload.get("role") == gate_label
            ]
        )

    async def entry_types(self) -> list[str]:
        async with self.postgres.get_session() as session:
            return [e.entry_type for e in await self.repository.read_all(session)]


def review_brief(head_sha: str) -> GateBrief:
    return GateBrief(
        gate_class=GateClassType.VERIFICATION,
        title="Technical review of the spec",
        what_is_decided="Whether the spec is technically sound",
        options=(
            BriefOption(option_id="approve", description="Sound", impact="Work continues"),
            BriefOption(
                option_id="request_changes", description="Not sound", impact="Spec is revised"
            ),
        ),
        recommendation="approve",
        recommendation_reason="The spec follows the design",
        head_sha=head_sha,
        evidence=(EvidenceReference(kind="ci", reference="run 1", digest="c" * 64),),
        after_signoff="Work continues either way",
    )


_AGENTS: dict[str, str] = {}


class ScriptedRole:
    """Asks the scripted deciding role on Paperclip."""

    def __init__(self, desk: AgentDesk) -> None:
        company = desk.identity.company_id
        if company not in _AGENTS:
            _AGENTS[company] = desk.hire("Deciding role", "deciding_role.py")
        self._desk = desk
        self._agent = _AGENTS[company]
        self.asked = 0

    async def request_call(self, brief: RoleBrief) -> str | None:
        self.asked += 1
        body: dict[str, object] = {
            "options": [option.option_id for option in brief.options],
            "evidence": ["journey-note"],
        }
        issue = self._desk.assign(self._agent, f"Decide {uuid.uuid4().hex[:6]}", body)
        return self._desk.first_finished_run(self._agent, issue).stdout or None
