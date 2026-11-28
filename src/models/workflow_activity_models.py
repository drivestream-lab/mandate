"""Typed names and payloads for the activities Temporal workflows call."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.models.gate_models import PullRequestRef
from src.models.signoff_models import GateDecisionStateType, RecheckReport
from src.models.sweep_models import RepoBaseline, SweepReport


class ActivityNameType(StrEnum):
    """Every business-service activity a workflow may call, by name.

    A name is added here together with its input and output models and its registration in
    worker_main.py; a unit test fails when one is missing from the registry.
    """

    FILE_WORK_ITEM = "skeleton.file_work_item"
    SEED_SWEEP_CHECKPOINTS = "skeleton.seed_sweep_checkpoints"
    OPEN_GATE = "skeleton.open_gate"
    CHECK_UNSIGNED_GATE = "skeleton.check_unsigned_gate"
    SETTLE_GATE = "skeleton.settle_gate"
    REFUSE_APP_AT_L0 = "skeleton.refuse_app_at_l0"
    RECHECK_OPEN_GATES = "skeleton.recheck_open_gates"
    SWEEP_GOVERNED_BRANCHES = "skeleton.sweep_governed_branches"


class ActivityInput(BaseModel):
    """Base of every activity input model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ActivityOutput(BaseModel):
    """Base of every activity output model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SkeletonStageType(StrEnum):
    """The two gates the walking skeleton signs: the PRD, then the wave built on it."""

    PRD = "prd"
    WAVE = "wave"


class SkeletonWorkItem(BaseModel):
    """The work item as filed in Paperclip: the pull requests of one toy PRD and one toy wave.

    The PRD pull request is upstream of the wave's. `baselines` are the rulesets and branch
    protection the sweep compares with, supplied by the caller.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    work_item_id: UUID
    initiative: str = Field(min_length=1)
    deciding_role: str = Field(min_length=1)
    prd_pull: PullRequestRef
    prd_path: str = Field(min_length=1)
    wave_paths: tuple[str, ...] = Field(min_length=1, description="The files the wave changes")
    wave_pull: PullRequestRef
    refusal_pull: PullRequestRef
    sweep_repos: tuple[str, ...] = Field(min_length=1)
    baselines: tuple[RepoBaseline, ...]


class WalkingSkeletonInput(ActivityInput):
    """What starts the walking-skeleton workflow."""

    work_item: SkeletonWorkItem


class FileWorkItemInput(ActivityInput):
    work_item: SkeletonWorkItem


class WorkItemFiled(ActivityOutput):
    issue_id: str


class SkeletonStepInput(ActivityInput):
    """A step that needs only the work item's Paperclip issue."""

    issue_id: str = Field(min_length=1)
    prd_gate_id: UUID | None = None


class SkeletonStageInput(ActivityInput):
    """A step on one stage's gate."""

    issue_id: str = Field(min_length=1)
    stage: SkeletonStageType
    prd_gate_id: UUID | None = None


class SkeletonGateInput(ActivityInput):
    """A step on one stage's gate once it is open."""

    issue_id: str = Field(min_length=1)
    stage: SkeletonStageType
    gate_id: UUID
    prd_gate_id: UUID | None = None


class SeedReport(ActivityOutput):
    seeded: tuple[str, ...]
    already_present: tuple[str, ...]


class GateOpened(ActivityOutput):
    gate_id: UUID
    sealed_entry_hash: str
    call_on_pull_request: bool


class CheckedGate(ActivityOutput):
    state: GateDecisionStateType
    head_sha: str
    reason: str


class GateSettled(ActivityOutput):
    state: str
    reason: str
    head_sha: str | None
    merge_commit: str | None
    evidence_commit: str | None


class L0Refusal(ActivityOutput):
    state: GateDecisionStateType
    reason: str


class RecheckResult(ActivityOutput):
    report: RecheckReport


class SweepResult(ActivityOutput):
    report: SweepReport


class StageSummary(ActivityOutput):
    stage: SkeletonStageType
    gate_id: UUID
    before_signoff: CheckedGate
    settled: GateSettled


class WalkingSkeletonResult(ActivityOutput):
    """What the workflow did, step by step."""

    issue_id: str
    seed: SeedReport
    stages: tuple[StageSummary, ...]
    l0_refusal: L0Refusal
    rechecks: tuple[RecheckReport, ...]
    sweeps: tuple[SweepReport, ...]
