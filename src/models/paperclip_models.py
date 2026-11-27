"""Paperclip models: what Mandate sends to Paperclip and reads back from it."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _PaperclipRecord(BaseModel):
    """A record read from Paperclip: camelCase on the wire, unknown fields ignored."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="ignore"
    )


class PaperclipHealth(_PaperclipRecord):
    """What Paperclip reports about itself without credentials."""

    status: str
    commit: str | None = None


class PaperclipRun(_PaperclipRecord):
    """A run Mandate obtained by waking its own agent; every write happens inside one."""

    id: str
    agent_id: str
    status: str


class PaperclipIssue(_PaperclipRecord):
    """An issue as Paperclip holds it."""

    id: str
    identifier: str | None = None
    title: str
    description: str | None = None
    status: str
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
    kind: str
    status: str
    idempotency_key: str | None = None
    created_by_agent_id: str | None = None
    resolved_by_user_id: str | None = None
    resolved_by_agent_id: str | None = None
    result: QuestionResult | None = None


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
