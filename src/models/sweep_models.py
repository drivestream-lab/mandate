"""Sweep models: what a merge looked like on GitHub, what the gate rulesets should be, and what
one sweep found and did."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

_NON_BLANK = r"\S"
_SHA = r"^[0-9a-f]{40}$"
_DIGEST = r"^[0-9a-f]{64}$"


class BranchCommit(BaseModel):
    """A commit on a governed branch and its parents (the first is the line merged into). Its date
    and committer are never read: both are set by whoever pushed it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sha: str = Field(pattern=_SHA)
    parents: tuple[str, ...]


class CompareResult(BaseModel):
    """How a branch's tip stands against the checkpoint, as GitHub's compare reports it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    ahead_by: int = Field(ge=0)
    merge_base: str = Field(pattern=_SHA)


class WalkPlan(BaseModel):
    """What a sweep with a checkpoint walks: back from the tip to `stop_at`, at most `limit`
    first parents, and whether the branch was rewritten since the checkpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nothing_to_judge: bool
    rewritten: bool
    stop_at: str | None
    limit: int = Field(ge=0)


class PullMerge(BaseModel):
    """A merged pull request that GitHub associates with a commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: int = Field(gt=0)
    node_id: str = Field(min_length=1)
    base_ref: str = Field(min_length=1)
    head_sha: str = Field(pattern=_SHA)
    merge_commit_sha: str | None
    merged_at: datetime
    merged_by: str | None


class HeadStatus(BaseModel):
    """One mandate/gate-decision status posted on a commit: its state, who posted it and when."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    creator: str | None
    created_at: datetime


class MergeObservation(BaseModel):
    """A merge into a governed branch with everything needed to judge it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    merge_commit: str = Field(pattern=_SHA)
    head_sha: str = Field(pattern=_SHA, description="The head that was merged")
    merged_by: str | None
    merged_at: datetime
    pull_number: int | None = Field(
        description="None for a commit that is not a merged pull request's merge commit"
    )
    node_id: str | None = Field(description="The merged pull request's node id, for a revert")
    statuses: tuple[HeadStatus, ...]


class MergeVerdictType(StrEnum):
    """What a merge amounts to once judged."""

    GUARDED = "guarded"
    BREACH = "breach"
    EMERGENCY_EXCEPTION = "emergency_exception"


class RulesetBaseline(BaseModel):
    """One ruleset the repository is allowed to have, by id and the digest of its content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_id: int = Field(gt=0)
    digest: str = Field(pattern=_DIGEST)


class ProtectionBaseline(BaseModel):
    """What a governed branch's protection must be: a digest, or None for no protection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str = Field(min_length=1)
    digest: str | None = Field(pattern=_DIGEST)


class RepoBaseline(BaseModel):
    """The gate rulesets and branch protection a repository is allowed to have, as supplied by
    the caller from what a decided Launchpad run applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(min_length=1, pattern=_NON_BLANK)
    rulesets: tuple[RulesetBaseline, ...] = ()
    protections: tuple[ProtectionBaseline, ...] = ()


class GovernanceFinding(BaseModel):
    """One way a repository's rulesets or branch protection differ from its baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    subject: str = Field(description="What differs, as a stable key (a ruleset or a branch)")
    reason: str


class SweepConfig(BaseModel):
    """What one sweep is told: where to look, from when, who may merge in an emergency, and what
    the gate rulesets must be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repos: tuple[str, ...] = Field(min_length=1)
    own_repos: frozenset[str] = Field(
        default=frozenset(),
        description="Mandate's own repositories, where an emergency merge may be",
    )
    emergency_humans: frozenset[str] = Field(
        default=frozenset(), description="Logins of the named emergency humans"
    )
    mandate_login: str = Field(min_length=1, description="The login that posts the required check")
    max_depth: int = Field(
        default=50,
        gt=0,
        description="How many landings back a branch is walked: the first sweep goes this far, "
        "and a later one fails if its checkpoint is not reached within it",
    )
    baselines: tuple[RepoBaseline, ...] = ()


class BreachKindType(StrEnum):
    """The kinds of finding a sweep records."""

    REWRITTEN_BRANCH = "rewritten-branch"
    UNGUARDED_MERGE = "unguarded-merge"
    EMERGENCY_MERGE = "emergency-merge"
    GOVERNANCE_CHANGE = "governance-change"


class RecordedFinding(BaseModel):
    """A finding the sweep recorded in the ledger just now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: BreachKindType
    repo: str
    subject: str
    detail: str


class OpenedRevert(BaseModel):
    """A revert pull request opened for an unguarded merge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    reverted_pull: int
    revert_pull: int


class SweepEscalation(BaseModel):
    """Something the owner must look at now."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str
    subject: str
    reason: str


class SweepReport(BaseModel):
    """What one sweep recorded, escalated and answered. A finding recorded by an earlier sweep is
    not repeated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[RecordedFinding, ...]
    escalations: tuple[SweepEscalation, ...]
    reverts: tuple[OpenedRevert, ...]
    limits: tuple[str, ...] = Field(
        default=(), description="What this sweep cannot see, stated once per sweep"
    )
