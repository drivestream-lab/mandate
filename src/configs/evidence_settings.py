"""Settings for run-signed evidence: which signer workflow Mandate trusts, and at which ref."""

from typing import ClassVar

from pydantic import Field, field_validator

from src.configs.base_settings import BaseSettings

SIGNER_ISSUER = "https://token.actions.githubusercontent.com"
"""The OIDC issuer of GitHub Actions; a certificate from any other issuer is refused."""


class EvidenceSettings(BaseSettings):
    """The one workflow whose attestations count as evidence, pinned to a tag."""

    PREFIX: ClassVar[str] = "EVIDENCE"

    verify_repository: str = Field(
        default="drivestream-lab/mandate-verify", pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )
    workflow_path: str = Field(default=".github/workflows/verify.yml", min_length=1)
    signer_ref: str = Field(
        default="refs/tags/evidence-1", description="The pinned tag of the signer workflow"
    )
    signer_commit: str = Field(
        default="73eac8ac292c1e520b2ce4b2e457e823c38c7fb4",
        pattern=r"^[0-9a-f]{40}$",
        description="The commit the signer tag must point at; the trust root is this commit",
    )
    api_url: str = Field(default="https://api.github.com")
    request_timeout_seconds: float = Field(default=60.0, gt=0)

    @field_validator("signer_ref")
    @classmethod
    def _must_be_a_tag(cls, value: str) -> str:
        if not value.startswith("refs/tags/") or len(value) <= len("refs/tags/"):
            raise ValueError("the signer must be pinned to a tag (refs/tags/<name>)")
        return value

    @property
    def signer_identity(self) -> str:
        """The exact workflow identity a certificate must carry."""
        return f"https://github.com/{self.verify_repository}/{self.workflow_path}@{self.signer_ref}"

    @property
    def signer_tag(self) -> str:
        return self.signer_ref.removeprefix("refs/tags/")
