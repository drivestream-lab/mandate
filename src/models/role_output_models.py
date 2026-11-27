"""What a role hands back to Mandate: a deciding role's call and a coder's result.

These are the schemas Mandate reads role output with. The deterministic test agents build
their output with the same models, so a change here breaks them in the same pull request.
An output that does not fit its schema is treated as missing, never repaired.
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class RoleOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DecidingRoleCall(RoleOutput):
    """A deciding role's structured call: the option it picks, why, and the evidence it cites."""

    option: str = Field(min_length=1)
    reasons: tuple[str, ...] = Field(min_length=1)
    evidence_cited: tuple[str, ...] = Field(min_length=1)


class CoderResult(RoleOutput):
    """What a coding role reports after its work on a branch."""

    summary: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    changed_files: tuple[str, ...] = Field(min_length=1)


def read_role_output[M: RoleOutput](model: type[M], text: str | None) -> M | None:
    """The output as `model`, or None when it is absent or does not fit the schema."""
    if not text:
        return None
    try:
        return model.model_validate_json(text)
    except ValidationError:
        return None
