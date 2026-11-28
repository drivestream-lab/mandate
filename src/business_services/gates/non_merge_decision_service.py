"""Non-merge decisions: asked where the artifact lives, sealed first, recorded, never blocking.

A technical review or clarification checkpoint is a review on the pull request; triage, hiring
or adding a repo is a Paperclip question. Either way the deciding role's call is sealed in the
ledger before anything is posted. Opening returns at once and nothing waits on the answer.
When a holder has decided, the decision is written to the ledger with that holder, once.
Mandate never decides here: it posts the question and records what a holder did.
"""

from datetime import datetime
from uuid import UUID

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.gate_opening_service import GateOpeningService
from src.business_services.gates.sealed_call_service import (
    DecidingRoleCallSource,
    SealedCallService,
)
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.database.postgres.repository.gates.gate_repository import GateRepository
from src.database.postgres.repository.ledger.ledger_repository import LedgerRepository
from src.engine.gates.brief import render_brief
from src.engine.gates.non_merge_rules import ReadDecision
from src.exceptions.app_exceptions import BaseAppException
from src.infra_services.github_app_service import GitHubAppService
from src.infra_services.paperclip_service import PaperclipService
from src.infra_services.postgres_service import PostgresService
from src.models.gate_models import GateBrief, OpenedGate, PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import (
    DecisionOption,
    DecisionRecord,
    RungType,
    StoredLedgerEntry,
)
from src.models.paperclip_models import NewQuestion, PaperclipQuestion, QuestionOption

_WORKFLOW_VERSION = "non-merge-decision/1"
_IDENTITY_VERSION = "recorded-from-source"


class DecisionNotOfferedError(BaseAppException):
    """A holder chose something the brief did not offer."""

    def __init__(self, option_id: str) -> None:
        super().__init__(
            code="DECISION_NOT_OFFERED",
            message=f"the decision {option_id} is not one of the options offered",
            status_code=409,
        )


class _ReviewRequestPoster:
    """Posts a brief as a comment review on a pull request."""

    def __init__(self, github: GitHubAppService) -> None:
        self._github = github

    async def post_brief(self, pull_request: PullRequestRef, body: str) -> None:
        await self._github.post_review_request(pull_request, body)


class NonMergeDecisionService(BaseBusinessService):
    """Opens and records decisions that are not merges."""

    @inject
    def __init__(
        self,
        postgres_service: PostgresService,
        gates: GateRepository,
        sealed_calls: SealedCallService,
        opening: GateOpeningService,
        ledger: LedgerAppendService,
        ledger_repository: LedgerRepository,
    ) -> None:
        super().__init__()
        self._postgres = postgres_service
        self._gates = gates
        self._sealed_calls = sealed_calls
        self._opening = opening
        self._ledger = ledger
        self._ledger_repository = ledger_repository

    async def ask_on_pull_request(
        self,
        work_item_id: UUID,
        brief: GateBrief,
        pull_request: PullRequestRef,
        source: DecidingRoleCallSource,
        github: GitHubAppService,
        stamp: VersionStamp,
    ) -> OpenedGate:
        """Seal the role's call, then ask for a review on the pull request. Does not wait."""
        return await self._opening.open_gate(
            work_item_id, brief, pull_request, source, _ReviewRequestPoster(github), stamp
        )

    async def ask_in_paperclip(
        self,
        work_item_id: UUID,
        brief: GateBrief,
        issue_id: str,
        question_id: str,
        source: DecidingRoleCallSource,
        paperclip: PaperclipService,
        stamp: VersionStamp,
    ) -> tuple[OpenedGate, PaperclipQuestion]:
        """Seal the role's call, then open a question in Paperclip. Does not wait."""
        call = await self._sealed_calls.obtain_call(source, brief)
        async with self._postgres.transaction() as session:
            gate_id = await self._gates.open_gate(session, work_item_id, brief.gate_class.value)
            sealed = await self._sealed_calls.seal_in(session, gate_id, brief.head_sha, call, stamp)
        body = render_brief(brief, call)
        run = await paperclip.open_run(str(work_item_id), f"decision:{gate_id}")
        question = await paperclip.open_question(
            run,
            str(work_item_id),
            f"decision:{gate_id}",
            issue_id,
            NewQuestion(
                question_id=question_id,
                title=brief.title,
                prompt=body,
                options=tuple(
                    QuestionOption(id=option.option_id, label=option.description)
                    for option in brief.options
                ),
            ),
        )
        return OpenedGate(gate_id=gate_id, sealed=sealed, brief_body=body), question

    async def record_decision(
        self,
        brief: GateBrief,
        read: ReadDecision,
        rung: RungType,
        decided_at: datetime,
        stamp: VersionStamp,
    ) -> StoredLedgerEntry | None:
        """Write the holder's decision with their identity, once; None when already there."""
        if read.option_id not in {option.option_id for option in brief.options}:
            raise DecisionNotOfferedError(read.option_id)
        role = f"{brief.gate_class.value} decision"
        async with self._postgres.get_session() as session:
            existing = await self._ledger_repository.find_decision(
                session, read.holder, role, brief.head_sha
            )
        if existing is not None:
            return None
        record = DecisionRecord(
            actor=read.holder,
            role=role,
            rung=rung,
            options_offered=tuple(
                DecisionOption(option_id=option.option_id, description=option.description)
                for option in brief.options
            ),
            choice=read.option_id,
            reasons=(f"decided by {read.holder} where the artifact lives",),
            evidence=(),
            target_version=brief.head_sha,
            workflow_version=_WORKFLOW_VERSION,
            model_version=_IDENTITY_VERSION,
            decided_at=read.decided_at or decided_at,
        )
        return await self._ledger.append_decision(record, stamp)
