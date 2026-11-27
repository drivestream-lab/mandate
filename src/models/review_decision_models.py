"""A human review decision, in the shape the ledger imports."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LedgerEntryType(StrEnum):
    """Ledger entry types a hand-recorded decision may use."""

    DECISION = "decision"


class ReviewChoiceType(StrEnum):
    """What the human reviewer decided about a merged pull request."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    REJECTED = "rejected"


class ReviewVersionStamp(BaseModel):
    """The version stamp of the review: what produced the reviewed change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mandate_release: str = Field(min_length=1)
    rules_version: str = Field(min_length=1)


class ReviewDecisionEntry(BaseModel):
    """One review decision as a ledger entry, before the ledger adds sequence and hashes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_type: LedgerEntryType = LedgerEntryType.DECISION
    actor: str = Field(min_length=1)
    choice: ReviewChoiceType
    target_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    pull_request: str = Field(min_length=1)
    version_stamp: ReviewVersionStamp
