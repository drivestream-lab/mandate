"""Signoff models: a pull request as read from GitHub, who holds a gate, and what the check says."""

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.gate_models import PullRequestRef
from src.models.ledger_models import RungType

_NON_BLANK = r"\S"
_SHA = r"^[0-9a-f]{40}$"

GATE_DECISION_CONTEXT = "mandate/gate-decision"
"""The name of the one required check on develop and main."""


class ReviewStateType(StrEnum):
    """The states GitHub reports for a pull request review."""

    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    COMMENTED = "COMMENTED"
    DISMISSED = "DISMISSED"
    PENDING = "PENDING"


class ReviewerKindType(StrEnum):
    """The kinds of account GitHub reports for a reviewer."""

    USER = "User"
    BOT = "Bot"
    ORGANIZATION = "Organization"
    MANNEQUIN = "Mannequin"


GOVERNED_BRANCHES = frozenset({"develop", "main"})
"""The lines every merge into which is a gate."""


class PullReview(BaseModel):
    """One review on a pull request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    review_id: int
    reviewer: str = Field(min_length=1)
    reviewer_kind: ReviewerKindType
    state: ReviewStateType
    commit_id: str = Field(pattern=_SHA)
    body: str
    submitted_at: datetime


class PullRequestSnapshot(BaseModel):
    """What the check reads: the head, the labels, the ready state and every review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: PullRequestRef
    base_ref: str = Field(min_length=1, description="The branch the pull request merges into")
    head_sha: str = Field(pattern=_SHA)
    labels: tuple[str, ...]
    is_draft: bool
    reviews: tuple[PullReview, ...]


class OpenPull(BaseModel):
    """An open pull request and the branch it merges into."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ref: PullRequestRef
    base_ref: str


class GateRule(BaseModel):
    """A gate as the check knows it: its label, its rung and who holds it at that rung."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, pattern=_NON_BLANK)
    branch: str = Field(min_length=1, description="The branch whose merge this gate decides")
    rung: RungType
    holders: frozenset[str] = Field(min_length=1, description="Logins that may sign this gate")


class Attestation(BaseModel):
    """What an Approve's body must carry: initiative, head, digests, artifact paths, and the
    gate, repository and pull request it signs. Every field is required; none may be added."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initiative: str = Field(min_length=1, pattern=_NON_BLANK)
    head: str = Field(pattern=_SHA)
    gate: str = Field(min_length=1, pattern=_NON_BLANK)
    repo: str = Field(min_length=1, pattern=_NON_BLANK)
    pull_request: int = Field(gt=0)
    digests: tuple[str, ...] = Field(min_length=1, description="Hex SHA-256 of each artifact")
    artifact_paths: tuple[str, ...] = Field(min_length=1)

    @field_validator("digests")
    @classmethod
    def _digests_are_sha256(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in value):
            raise ValueError("a digest must be a lowercase hex SHA-256")
        return value


class SignoffReading(BaseModel):
    """A complete signoff on the current head: label, attested Approve and ready, by a holder."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signer: str
    label: str
    head_sha: str
    signed_at: datetime
    attestation: Attestation


class GateDecisionStateType(StrEnum):
    """What Mandate posts on the head."""

    SUCCESS = "success"
    FAILURE = "failure"


class SignoffAssessment(BaseModel):
    """The result of reading a pull request against a gate: a signoff, or the reason for none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signoff: SignoffReading | None
    reason: str | None


class GateDecisionOutcome(BaseModel):
    """What the check posted on a head, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: GateDecisionStateType
    head_sha: str
    reason: str
    signer: str | None
