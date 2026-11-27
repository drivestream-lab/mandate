"""Programme models: the configuration Launchpad keeps in a meta repo, and what Mandate makes of it."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RungType(StrEnum):
    """How far a gate has been handed from people to its deciding role."""

    L0 = "L0"
    L2 = "L2"
    L3 = "L3"


class ReadinessCheckType(StrEnum):
    """What readiness looks at."""

    ROLE_AGENT = "role_agent"
    REPOSITORY_ACCESS = "repository_access"
    WORKFLOW = "workflow"
    MANDATE_AGENT_LIMITS = "mandate_agent_limits"


class _Config(BaseModel):
    """Launchpad's files carry keys Mandate does not read; those are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class RoleSetup(_Config):
    """A role of the workflow and the Paperclip agent filling it."""

    name: str = Field(min_length=1)
    agent: str = Field(min_length=1)


class DecisionOwners(_Config):
    """The named human who owns decisions for each gate class."""

    intent: str = Field(min_length=1)
    design: str = Field(min_length=1)
    release: str = Field(min_length=1)
    housekeeping: str = Field(min_length=1)


class WorkflowPin(_Config):
    """The delivery workflow the programme is pinned to."""

    contract: str = Field(min_length=1)
    skills_repo: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ProgrammeConfig(_Config):
    """A meta repo's config/programme.yaml."""

    programme: str = Field(min_length=1)
    programme_slug: str = Field(min_length=1)
    org: str = Field(min_length=1)
    meta_repo: str = Field(min_length=1)
    repos: tuple[str, ...] = Field(min_length=1)
    roles: tuple[RoleSetup, ...] = Field(min_length=1)
    decision_owners: DecisionOwners
    workflow: WorkflowPin
    starting_rung: RungType


class Programme(BaseModel):
    """A programme as created: its Paperclip project and the configuration it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    meta_commit: str
    config: ProgrammeConfig


class ReadinessFailure(BaseModel):
    """One thing that is not ready, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: ReadinessCheckType
    subject: str
    cause: str


class ReadinessReport(BaseModel):
    """The outcome of every readiness check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    failures: tuple[ReadinessFailure, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.failures
