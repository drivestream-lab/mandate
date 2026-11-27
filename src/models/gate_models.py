"""Gate models: the brief a gate shows, the gate classes, and a call sealed for a gate."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.models.ledger_models import EvidenceReference

_NON_BLANK = r"\S"


class GateClassType(StrEnum):
    """The kinds of gate a brief is written for."""

    INTENT = "intent"
    DESIGN = "design"
    VERIFICATION = "verification"
    HOUSEKEEPING = "housekeeping"


BLIND_FIRST_GATES = frozenset({GateClassType.INTENT, GateClassType.DESIGN})
"""Gates where the deciding role's call stays out of the brief until the holder has signed."""


class BriefOption(BaseModel):
    """One option put to the holder, with what choosing it would change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    option_id: str = Field(min_length=1, pattern=_NON_BLANK)
    description: str = Field(min_length=1, pattern=_NON_BLANK)
    impact: str = Field(min_length=1, pattern=_NON_BLANK)


class GateBrief(BaseModel):
    """What a gate's brief says, before any deciding-role call is considered."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_class: GateClassType
    title: str = Field(min_length=1, pattern=_NON_BLANK)
    what_is_decided: str = Field(min_length=1, pattern=_NON_BLANK)
    options: tuple[BriefOption, ...] = Field(min_length=1)
    recommendation: str = Field(min_length=1, description="The option_id the author recommends")
    recommendation_reason: str = Field(min_length=1, pattern=_NON_BLANK)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$", description="The commit the evidence is for")
    evidence: tuple[EvidenceReference, ...]
    after_signoff: str = Field(min_length=1, pattern=_NON_BLANK)

    @model_validator(mode="after")
    def _recommendation_is_an_option(self) -> "GateBrief":
        ids = [option.option_id for option in self.options]
        if len(set(ids)) != len(ids):
            raise ValueError("an option appears more than once")
        if self.recommendation not in ids:
            raise ValueError("the recommendation is not one of the options")
        return self


class PullRequestRef(BaseModel):
    """The pull request a brief is posted on."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo: str = Field(min_length=1)
    number: int = Field(gt=0)


class SealedCall(BaseModel):
    """What the opener holds after sealing: enough to reveal the call later, and nothing public.

    The call and nonce live with the holder of this record (never on the pull request). The
    ledger holds only the digest.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: UUID
    sealed_entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    call_json: str | None = Field(description="The call as JSON, or None when there was none")
    nonce: str | None


class OpenedGate(BaseModel):
    """A gate that has been opened: its id, the sealed call and where the brief was posted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: UUID
    sealed: SealedCall
    brief_body: str
