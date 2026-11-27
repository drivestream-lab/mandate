"""Paperclip models: what Mandate sends to Paperclip and reads back from it."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class HealthStatusType(StrEnum):
    """What Paperclip's health report says about itself."""

    OK = "ok"
    STARTING = "starting"


class RunStatusType(StrEnum):
    """The states of a run in the pinned Paperclip release."""

    QUEUED = "queued"
    SCHEDULED_RETRY = "scheduled_retry"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class IssueStatusType(StrEnum):
    """The states of an issue in the pinned Paperclip release."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class InteractionKindType(StrEnum):
    """The kinds of card an issue thread holds."""

    SUGGEST_TASKS = "suggest_tasks"
    ASK_USER_QUESTIONS = "ask_user_questions"
    REQUEST_CONFIRMATION = "request_confirmation"
    REQUEST_CHECKBOX_CONFIRMATION = "request_checkbox_confirmation"
    REQUEST_ITEM_VERDICTS = "request_item_verdicts"
    CONNECTION_INTENT = "connection_intent"
    SUGGEST_ROUTINE = "suggest_routine"
    PROPOSE_RESPONSIBILITY_BAR = "propose_responsibility_bar"
    PROPOSE_AUTOMATION = "propose_automation"
    PROPOSE_DASHBOARD_CHANGES = "propose_dashboard_changes"


class InteractionStatusType(StrEnum):
    """The states of a card in an issue thread."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class WakeSourceType(StrEnum):
    """Why an agent is woken; Mandate only wakes its agent on demand."""

    ON_DEMAND = "on_demand"


class WakeTriggerType(StrEnum):
    """How the wake was triggered."""

    MANUAL = "manual"


class ContinuationPolicyType(StrEnum):
    """What follows an answer; Mandate asks without waking anyone."""

    NONE = "none"


class ResolverPolicyType(StrEnum):
    """Who may answer a card; Mandate's questions are for people only."""

    HUMAN_ONLY = "human_only"


class SelectionModeType(StrEnum):
    """How many options a question lets the holder pick."""

    SINGLE = "single"


class _PaperclipRecord(BaseModel):
    """A record read from Paperclip: camelCase on the wire, unknown fields ignored."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="ignore"
    )


class PaperclipHealth(_PaperclipRecord):
    """What Paperclip reports about itself without credentials."""

    status: HealthStatusType
    commit: str | None = None


class PaperclipRun(_PaperclipRecord):
    """A run Mandate obtained by waking its own agent; every write happens inside one."""

    id: str
    agent_id: str
    status: RunStatusType


class PaperclipIssue(_PaperclipRecord):
    """An issue as Paperclip holds it."""

    id: str
    identifier: str | None = None
    title: str
    description: str | None = None
    status: IssueStatusType
    project_id: str | None = None
    assignee_agent_id: str | None = None
    created_by_agent_id: str | None = None
    origin_run_id: str | None = None


class PaperclipComment(_PaperclipRecord):
    """A comment on an issue."""

    id: str
    issue_id: str
    body: str
    author_agent_id: str | None = None


class QuestionAnswer(_PaperclipRecord):
    """The options chosen for one question."""

    question_id: str
    option_ids: tuple[str, ...]


class QuestionResult(_PaperclipRecord):
    """The recorded response to a question."""

    answers: tuple[QuestionAnswer, ...] = ()


class PaperclipQuestion(_PaperclipRecord):
    """A question card in an issue thread: what was asked, its status, and who answered."""

    id: str
    issue_id: str
    kind: InteractionKindType
    status: InteractionStatusType
    idempotency_key: str | None = None
    created_by_agent_id: str | None = None
    resolved_by_user_id: str | None = None
    resolved_by_agent_id: str | None = None
    result: QuestionResult | None = None


class AgentPermissions(_PaperclipRecord):
    """The permission flags on an agent record; they do not deny interactions or skills."""

    can_create_agents: bool = False


class PaperclipAgent(_PaperclipRecord):
    """An agent as Paperclip holds it."""

    id: str
    name: str
    status: str
    lifecycle_state: str
    permissions: AgentPermissions = AgentPermissions()


class EffectiveInteractions(_PaperclipRecord):
    """What an agent may do to other agents' work once overrides are applied."""

    can_assign_tasks_to_agents: bool
    can_configure_other_agents: bool


class InteractionPermissions(_PaperclipRecord):
    """An agent's interaction permissions."""

    effective: EffectiveInteractions


class SkillDecision(_PaperclipRecord):
    """Paperclip's own answer on whether the calling agent may take a skill action."""

    allowed: bool
    action: str
    reason: str


class PaperclipProject(_PaperclipRecord):
    """A project as Paperclip holds it."""

    id: str
    name: str
    description: str | None = None


class QuestionOption(BaseModel):
    """One option of a question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)


class NewIssue(BaseModel):
    """An issue Mandate files. It has no assignee: Mandate does not assign work."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    description: str = ""


class NewQuestion(BaseModel):
    """A question Mandate opens on an issue; only a person can answer it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    options: tuple[QuestionOption, ...] = Field(min_length=2)
    addressee_user_id: str | None = None


class PaperclipRequest(BaseModel):
    """A request body: camelCase on the wire, nothing unexpected, unset optionals left out."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)


class WakeupRequest(PaperclipRequest):
    """Wake Mandate's own agent to obtain a run."""

    source: WakeSourceType = WakeSourceType.ON_DEMAND
    trigger_detail: WakeTriggerType = WakeTriggerType.MANUAL
    reason: str
    idempotency_key: str


class IssueRequest(PaperclipRequest):
    """Create an issue."""

    title: str
    description: str
    idempotency_key: str
    project_id: str | None = None


class CommentRequest(PaperclipRequest):
    """Add a comment."""

    body: str
    client_request_id: str


class QuestionSpec(PaperclipRequest):
    """One single-choice question."""

    id: str
    prompt: str
    selection_mode: SelectionModeType = SelectionModeType.SINGLE
    required: bool = True
    options: tuple[QuestionOption, ...]


class QuestionPayload(PaperclipRequest):
    """The body of a question card."""

    version: int = 1
    title: str
    questions: tuple[QuestionSpec, ...]


class QuestionRequest(PaperclipRequest):
    """Open a question card on an issue."""

    kind: InteractionKindType = InteractionKindType.ASK_USER_QUESTIONS
    continuation_policy: ContinuationPolicyType = ContinuationPolicyType.NONE
    resolver_policy: ResolverPolicyType = ResolverPolicyType.HUMAN_ONLY
    idempotency_key: str
    payload: QuestionPayload
    addressee_user_id: str | None = None


class NewProject(BaseModel):
    """A project Mandate creates for a programme."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""


class ProjectRequest(PaperclipRequest):
    """Create a project."""

    name: str
    description: str


class SkillEvaluationRequest(PaperclipRequest):
    """Ask Paperclip whether the calling agent may take a skill action."""

    action: str
