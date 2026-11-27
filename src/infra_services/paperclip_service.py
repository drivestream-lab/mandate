"""Mandate's client for Paperclip: every write happens inside a run Mandate woke on its own agent.

Rules this client keeps:
- It checks Paperclip's build commit (GET /api/health) against the one pinned release before it
  starts, and again before each run. An unreadable or different release stops all work; there is
  no default to fall back to.
- A write takes a PaperclipRun that this client opened with POST /api/agents/:id/wakeup. It sends
  the run's id as X-Paperclip-Run-Id and an idempotency key derived from the work item and the
  step. A run this client did not open is refused before anything is sent.
- It has no call that assigns work, creates agents or creates skills.
"""

import uuid

import httpx
from injector import NoInject, inject
from pydantic import BaseModel, TypeAdapter

from src.configs.paperclip_settings import PINNED_PAPERCLIP_COMMIT, PaperclipSettings
from src.engine.kernel.idempotency_key import derive_idempotency_key
from src.infra_services.base_infra_service import BaseInfraService
from src.logging import get_logger
from src.models.kernel_models import IdempotencyKey
from src.models.paperclip_models import (
    PaperclipRequest,
    CommentRequest,
    IssueRequest,
    HealthStatusType,
    InteractionKindType,
    InteractionPermissions,
    NewIssue,
    NewProject,
    NewQuestion,
    PaperclipAgent,
    PaperclipComment,
    PaperclipHealth,
    PaperclipIssue,
    PaperclipProject,
    PaperclipQuestion,
    PaperclipRun,
    QuestionPayload,
    ProjectRequest,
    QuestionRequest,
    QuestionSpec,
    SkillDecision,
    SkillPolicy,
    SkillEvaluationRequest,
    WakeupRequest,
)

logger = get_logger()

_MAX_ERROR_TEXT = 300


class PaperclipError(Exception):
    """Base for every refusal or failure of the Paperclip client."""


class UnrecognisedReleaseError(PaperclipError):
    """Paperclip's release is not the pinned one, or could not be read: Mandate stops."""


class WriteOutsideRunError(PaperclipError):
    """A write was attempted with a run this client did not open."""


class PaperclipRequestError(PaperclipError):
    """Paperclip answered a request with an error status."""

    def __init__(self, status_code: int, path: str, detail: str) -> None:
        super().__init__(f"Paperclip answered {status_code} for {path}: {detail}")
        self.status_code = status_code
        self.path = path


def check_release(health: PaperclipHealth, pinned_commit: str) -> None:
    """Accept only a health report whose commit equals the pinned one, exactly.

    A missing commit, an abbreviated one or a different one is a stop.
    """
    if health.status is not HealthStatusType.OK:
        raise UnrecognisedReleaseError("Paperclip is starting; Mandate does not proceed")
    if not health.commit:
        raise UnrecognisedReleaseError("Paperclip did not report its build commit")
    if health.commit != pinned_commit:
        raise UnrecognisedReleaseError(
            f"Paperclip build {health.commit} is not the pinned release {pinned_commit}"
        )


def _comment_request_id(key: IdempotencyKey) -> str:
    """A UUID derived from the key: Paperclip's per-comment request id, so a repeat is one comment."""
    return str(uuid.UUID(hex=key.value[:32], version=4))


_JSON = {"Content-Type": "application/json"}
_COMMENTS = TypeAdapter(list[PaperclipComment])
_CARDS = TypeAdapter(list[dict[str, object]])
_PROJECTS = TypeAdapter(list[PaperclipProject])
_AGENTS = TypeAdapter(list[PaperclipAgent])


class PaperclipService(BaseInfraService):
    """Talks to Paperclip as Mandate's own agent, only inside its own runs."""

    @inject
    def __init__(
        self,
        settings: NoInject[PaperclipSettings | None] = None,
        *,
        pinned_commit: NoInject[str] = PINNED_PAPERCLIP_COMMIT,
    ) -> None:
        """`pinned_commit` is for tests that need another pin; it is never read from configuration."""
        self._settings = settings if settings is not None else PaperclipSettings.get_instance()
        self._pinned_commit = pinned_commit
        self._client: httpx.AsyncClient | None = None
        self._opened_runs: set[str] = set()

    @property
    def agent_id(self) -> str:
        """Mandate's own agent."""
        return self._settings.agent_id

    async def initialize(self) -> None:
        """Read the agent token, open the connection and refuse an unrecognised release."""
        if self._client is not None:
            return
        token = self._settings.token_file.read_text(encoding="utf-8").strip()
        client = httpx.AsyncClient(
            base_url=self._settings.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=self._settings.request_timeout_seconds,
        )
        try:
            await self._verify_release(client)
        except BaseException:
            await client.aclose()
            raise
        self._client = client
        logger.info("Paperclip client ready on the pinned release")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._opened_runs.clear()

    async def health_check(self) -> bool:
        """True when Paperclip is reachable on the pinned release; never raises."""
        try:
            await self._verify_release(self._ready())
        except (PaperclipError, httpx.HTTPError):
            return False
        return True

    async def verify_release(self) -> None:
        """Raise UnrecognisedReleaseError unless Paperclip runs the pinned release now."""
        await self._verify_release(self._ready())

    async def open_run(self, work_item_id: str, step: str) -> PaperclipRun:
        """Wake Mandate's own agent for this step and return the run its writes belong to."""
        client = self._ready()
        await self._verify_release(client)
        key = derive_idempotency_key(work_item_id, f"{step}:run")
        path = f"/api/agents/{self._settings.agent_id}/wakeup"
        request = WakeupRequest(reason=f"Mandate step {step}", idempotency_key=key.value)
        response = await client.post(
            path,
            content=request.to_json(),
            headers={"Idempotency-Key": key.value, **_JSON},
        )
        self._raise_for_status(response, path)
        run = self._parse(PaperclipRun, response, path)
        if run.agent_id != self._settings.agent_id:
            raise PaperclipError("Paperclip returned a run for a different agent")
        self._opened_runs.add(run.id)
        return run

    async def create_issue(
        self, run: PaperclipRun, work_item_id: str, step: str, issue: NewIssue
    ) -> PaperclipIssue:
        """File an issue in Mandate's company (and project, when set), unassigned."""
        key = derive_idempotency_key(work_item_id, f"{step}:issue")
        body = IssueRequest(
            title=issue.title,
            description=issue.description,
            idempotency_key=key.value,
            project_id=self._settings.project_id,
        )
        path = f"/api/companies/{self._settings.company_id}/issues"
        response = await self._write(run, path, key, body)
        return self._parse(PaperclipIssue, response, path)

    async def post_comment(
        self, run: PaperclipRun, work_item_id: str, step: str, issue_id: str, text: str
    ) -> PaperclipComment:
        """Add a comment to an issue."""
        key = derive_idempotency_key(work_item_id, f"{step}:comment")
        path = f"/api/issues/{issue_id}/comments"
        body = CommentRequest(body=text, client_request_id=_comment_request_id(key))
        response = await self._write(run, path, key, body)
        return self._parse(PaperclipComment, response, path)

    async def open_question(
        self, run: PaperclipRun, work_item_id: str, step: str, issue_id: str, question: NewQuestion
    ) -> PaperclipQuestion:
        """Open a single-choice question on an issue that only a person can answer."""
        key = derive_idempotency_key(work_item_id, f"{step}:question")
        body = QuestionRequest(
            idempotency_key=key.value,
            payload=QuestionPayload(
                title=question.title,
                questions=(
                    QuestionSpec(
                        id=question.question_id, prompt=question.prompt, options=question.options
                    ),
                ),
            ),
            addressee_user_id=question.addressee_user_id,
        )
        path = f"/api/issues/{issue_id}/interactions"
        response = await self._write(run, path, key, body)
        return self._parse(PaperclipQuestion, response, path)

    async def create_project(
        self, run: PaperclipRun, work_item_id: str, step: str, project: NewProject
    ) -> PaperclipProject:
        """Create a project in Mandate's company."""
        key = derive_idempotency_key(work_item_id, f"{step}:project")
        body = ProjectRequest(name=project.name, description=project.description)
        path = f"/api/companies/{self._settings.company_id}/projects"
        response = await self._write(run, path, key, body)
        return self._parse(PaperclipProject, response, path)

    async def list_projects(self) -> list[PaperclipProject]:
        path = f"/api/companies/{self._settings.company_id}/projects"
        return self._parse_list(_PROJECTS, await self._read(path), path)

    async def list_agents(self) -> list[PaperclipAgent]:
        path = f"/api/companies/{self._settings.company_id}/agents"
        return self._parse_list(_AGENTS, await self._read(path), path)

    async def get_agent(self, agent_id: str) -> PaperclipAgent:
        path = f"/api/agents/{agent_id}"
        return self._parse(PaperclipAgent, await self._read(path), path)

    async def get_interaction_permissions(self, agent_id: str) -> InteractionPermissions:
        path = f"/api/agents/{agent_id}/interaction-permissions"
        return self._parse(InteractionPermissions, await self._read(path), path)

    async def get_own_agent(self) -> PaperclipAgent:
        """The agent the token belongs to, as Paperclip sees it."""
        return await self.get_agent("me")

    async def get_skill_policy(self) -> SkillPolicy:
        path = f"/api/companies/{self._settings.company_id}/skill-policy"
        return self._parse(SkillPolicy, await self._read(path), path)

    async def evaluate_skill_action(self, action: str) -> SkillDecision:
        """Ask Paperclip whether Mandate's agent may take this skill action; it decides, not Mandate."""
        path = f"/api/companies/{self._settings.company_id}/skill-policy/evaluate"
        body = SkillEvaluationRequest(action=action)
        response = await self._ready().post(path, content=body.to_json(), headers=_JSON)
        self._raise_for_status(response, path)
        return self._parse(SkillDecision, response, path)

    async def get_issue(self, issue_id: str) -> PaperclipIssue:
        path = f"/api/issues/{issue_id}"
        return self._parse(PaperclipIssue, await self._read(path), path)

    async def list_comments(self, issue_id: str) -> list[PaperclipComment]:
        path = f"/api/issues/{issue_id}/comments"
        response = await self._read(path)
        try:
            return _COMMENTS.validate_json(response.content)
        except ValueError as error:
            raise PaperclipError(f"unexpected answer from Paperclip for {path}") from error

    async def list_questions(self, issue_id: str) -> list[PaperclipQuestion]:
        """The questions Mandate can read on an issue; cards of any other kind are left unread."""
        path = f"/api/issues/{issue_id}/interactions"
        response = await self._read(path)
        try:
            cards = _CARDS.validate_json(response.content)
            return [
                PaperclipQuestion.model_validate(card)
                for card in cards
                if card.get("kind") == InteractionKindType.ASK_USER_QUESTIONS
            ]
        except ValueError as error:
            raise PaperclipError(f"unexpected answer from Paperclip for {path}") from error

    def _ready(self) -> httpx.AsyncClient:
        if self._client is None:
            raise PaperclipError("the Paperclip client is not initialised")
        return self._client

    async def _verify_release(self, client: httpx.AsyncClient) -> None:
        try:
            response = await client.get("/api/health")
            response.raise_for_status()
            health = PaperclipHealth.model_validate_json(response.content)
        except (httpx.HTTPError, ValueError) as error:
            raise UnrecognisedReleaseError(
                f"Paperclip's release could not be read: {type(error).__name__}"
            ) from error
        check_release(health, self._pinned_commit)

    async def _write(
        self, run: PaperclipRun, path: str, key: IdempotencyKey, body: PaperclipRequest
    ) -> httpx.Response:
        if run.id not in self._opened_runs:
            raise WriteOutsideRunError("writes are allowed only inside a run this client opened")
        response = await self._ready().post(
            path,
            content=body.to_json(),
            headers={"X-Paperclip-Run-Id": run.id, "Idempotency-Key": key.value, **_JSON},
        )
        self._raise_for_status(response, path)
        return response

    async def _read(self, path: str) -> httpx.Response:
        response = await self._ready().get(path)
        self._raise_for_status(response, path)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, path: str) -> None:
        if response.is_success:
            return
        raise PaperclipRequestError(response.status_code, path, response.text[:_MAX_ERROR_TEXT])

    @staticmethod
    def _parse[M: BaseModel](model: type[M], response: httpx.Response, path: str) -> M:
        try:
            return model.model_validate_json(response.content)
        except ValueError as error:
            raise PaperclipError(f"unexpected answer from Paperclip for {path}") from error

    @staticmethod
    def _parse_list[T](
        adapter: TypeAdapter[list[T]], response: httpx.Response, path: str
    ) -> list[T]:
        try:
            return adapter.validate_json(response.content)
        except ValueError as error:
            raise PaperclipError(f"unexpected answer from Paperclip for {path}") from error
