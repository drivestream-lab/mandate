"""Kernel models: the version stamp, the idempotency key and the stamp field names."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


_NON_BLANK = r"\S"
"""Pattern for a string part: at least one non-space character, so a blank part is rejected."""


class StampFieldType(StrEnum):
    """The parts of a version stamp, as named when two stamps are compared."""

    CONTRACT = "contract"
    BLOCK_VERSIONS = "block_versions"
    SKILLS = "skills"
    RULES = "rules"
    AGENT_SETUP = "agent_setup"
    POLICY_REVISION = "policy_revision"
    MANDATE_RELEASE = "mandate_release"


class NamedVersion(BaseModel):
    """One versioned part of the stamp, such as a building block or a skill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1,
        pattern=_NON_BLANK,
        description="What is versioned, such as a block or skill name",
    )
    version: str = Field(
        min_length=1, pattern=_NON_BLANK, description="Its version or content digest"
    )


class VersionStamp(BaseModel):
    """What produced a step run or a ledger entry, so measures compare like with like.

    Every field is required and non-empty: an unknown part is a stop, never a default.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: str = Field(min_length=1, pattern=_NON_BLANK, description="Contract version")
    block_versions: tuple[NamedVersion, ...] = Field(description="Building block versions")
    skills: tuple[NamedVersion, ...] = Field(description="Skill versions")
    rules: str = Field(min_length=1, pattern=_NON_BLANK, description="Rules version")
    agent_setup: str = Field(
        min_length=1, pattern=_NON_BLANK, description="Agent setup version or digest"
    )
    policy_revision: str = Field(min_length=1, pattern=_NON_BLANK, description="Policy revision")
    mandate_release: str = Field(min_length=1, pattern=_NON_BLANK, description="Mandate release")

    @field_validator("block_versions", "skills")
    @classmethod
    def _sorted_and_unique(cls, value: tuple[NamedVersion, ...]) -> tuple[NamedVersion, ...]:
        """Order by name so equal stamps encode equally; a repeated name is an error."""
        names = [item.name for item in value]
        if len(set(names)) != len(names):
            raise ValueError("a name appears more than once")
        return tuple(sorted(value, key=lambda item: item.name))


class IdempotencyKey(BaseModel):
    """A key derived from a work item and a step; a repeat of the same step has one effect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str = Field(pattern=r"^[0-9a-f]{64}$", description="Hex SHA-256 of the canonical input")
