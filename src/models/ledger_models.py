"""Ledger models: decision and correction records, entries as sealed and as stored, and the
result of checking a chain."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from src.models.kernel_models import VersionStamp

_NON_BLANK = r"\S"
_HEX_SHA256 = r"^[0-9a-f]{64}$"

GENESIS_HASH = "0" * 64
"""What the first entry links to, so every written entry has a previous hash."""


class LedgerEntryType(StrEnum):
    """The kinds of entry the ledger writer appends."""

    DECISION = "decision"
    CORRECTION = "correction"


class RungType(StrEnum):
    """Who decides a gate: the human alone (L0), both independently (L1), or a role (L2, L3)."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class DecisionOption(BaseModel):
    """One option put to the decider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    option_id: str = Field(min_length=1, pattern=_NON_BLANK, description="Identifier of the option")
    description: str = Field(min_length=1, pattern=_NON_BLANK, description="What the option is")


class EvidenceReference(BaseModel):
    """A piece of evidence the decision relied on, pinned by digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1, pattern=_NON_BLANK, description="What sort of evidence")
    reference: str = Field(min_length=1, pattern=_NON_BLANK, description="Where to find it")
    digest: str = Field(pattern=_HEX_SHA256, description="Hex SHA-256 of the evidence content")


class DecisionRecord(BaseModel):
    """Everything a decision records, so anyone can later ask who decided what, and on what.

    The version stamp on the ledger entry carries the policy revision, skills and Mandate
    release. The stamp has no workflow or model version, so this record carries them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1, pattern=_NON_BLANK, description="Who decided")
    role: str = Field(min_length=1, pattern=_NON_BLANK, description="The role the actor held")
    rung: RungType = Field(description="The rung the gate was at")
    options_offered: tuple[DecisionOption, ...] = Field(
        min_length=1, description="The options put to the decider"
    )
    choice: str = Field(min_length=1, description="The option_id chosen")
    reasons: tuple[str, ...] = Field(min_length=1, description="Why the decider chose it")
    evidence: tuple[EvidenceReference, ...] = Field(description="Evidence relied on, possibly none")
    target_version: str = Field(
        min_length=1, pattern=_NON_BLANK, description="The version decided on, such as a commit"
    )
    workflow_version: str = Field(
        min_length=1, pattern=_NON_BLANK, description="Version of the workflow in force"
    )
    model_version: str = Field(
        min_length=1, pattern=_NON_BLANK, description="Version of the model that made the call"
    )
    decided_at: datetime = Field(description="When the decision was made, in UTC")

    @field_validator("reasons")
    @classmethod
    def _reasons_not_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not reason.strip() for reason in value):
            raise ValueError("a reason must not be blank")
        return value

    @field_validator("decided_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("decided_at must be timezone-aware UTC")
        return value

    @model_validator(mode="after")
    def _choice_was_offered(self) -> "DecisionRecord":
        offered = [option.option_id for option in self.options_offered]
        if len(set(offered)) != len(offered):
            raise ValueError("an option appears more than once")
        if self.choice not in offered:
            raise ValueError("the choice is not one of the options offered")
        return self


class CorrectionRecord(BaseModel):
    """A new entry that supersedes an earlier decision without changing it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corrects_entry_hash: str = Field(
        pattern=_HEX_SHA256, description="Hash of the entry this one corrects"
    )
    actor: str = Field(min_length=1, pattern=_NON_BLANK, description="Who made the correction")
    reason: str = Field(min_length=1, pattern=_NON_BLANK, description="Why it is being corrected")
    corrected_decision: DecisionRecord = Field(description="The decision as it should read")


class LedgerEntryDraft(BaseModel):
    """What the caller supplies for a new entry; the chain position is added when it is sealed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry_id: UUID = Field(description="Identity of the entry")
    entry_type: str = Field(min_length=1, pattern=_NON_BLANK, description="Kind of entry")
    payload: dict[str, JsonValue] = Field(description="The entry's content, JSON without floats")
    version_stamp: VersionStamp = Field(description="What produced the entry")


class LedgerPayloadEnvelope(BaseModel):
    """What the repository keeps in the payload column: the content with its version stamp."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: dict[str, JsonValue]
    version_stamp: VersionStamp


class SealedLedgerEntry(LedgerEntryDraft):
    """A draft linked to the entry before it and carrying its own hash."""

    previous_hash: str = Field(
        pattern=_HEX_SHA256, description="Hash of the entry before; the genesis hash for the first"
    )
    entry_hash: str = Field(pattern=_HEX_SHA256, description="Hash of this entry's content")


class StoredLedgerEntry(BaseModel):
    """An entry as read back from the database.

    The hash and stamp may be absent on a row written outside the writer; verification reports
    such a row rather than guessing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(description="Position assigned by the database; gaps are normal")
    entry_id: UUID
    entry_type: str
    payload: dict[str, JsonValue]
    version_stamp: VersionStamp | None
    previous_hash: str | None
    entry_hash: str | None
    recorded_at: datetime = Field(description="Database time of the insert; not covered by hash")


class ChainAnchor(BaseModel):
    """What the chain must start and end with, from outside the table (a signed checkpoint)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    head_hash: str = Field(
        pattern=_HEX_SHA256,
        description="Hash of the last entry; the first_previous_hash for an empty chain",
    )
    first_previous_hash: str = Field(
        default=GENESIS_HASH,
        pattern=_HEX_SHA256,
        description="Hash the first entry must link to; the genesis hash when checking from the start",
    )


class ChainProblemType(StrEnum):
    """Why a chain failed to verify."""

    UNHASHED_ENTRY = "unhashed_entry"
    MISSING_STAMP = "missing_stamp"
    MISSING_LINK = "missing_link"
    HASH_MISMATCH = "hash_mismatch"
    DUPLICATE_HASH = "duplicate_hash"
    FORK = "fork"
    BAD_START = "bad_start"
    UNREACHABLE_ENTRY = "unreachable_entry"
    SEQUENCE_ORDER = "sequence_order"
    HEAD_MISMATCH = "head_mismatch"


class ChainProblem(BaseModel):
    """One thing wrong with the chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    problem: ChainProblemType
    sequence: int | None = Field(description="Sequence of the entry concerned, if one")
    detail: str


class ChainVerification(BaseModel):
    """The outcome of walking a chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries_checked: int
    problems: tuple[ChainProblem, ...]

    @property
    def is_intact(self) -> bool:
        """True only when nothing at all was found wrong."""
        return not self.problems
