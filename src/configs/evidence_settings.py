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
        default="refs/heads/main",
        description="The branch of the signer workflow; its head, read live, is the trust root",
    )
    api_url: str = Field(default="https://api.github.com")
    request_timeout_seconds: float = Field(default=60.0, gt=0)

    @field_validator("signer_ref")
    @classmethod
    def _must_be_a_branch(cls, value: str) -> str:
        if not value.startswith("refs/heads/") or len(value) <= len("refs/heads/"):
            raise ValueError("the signer must be a branch (refs/heads/<name>)")
        return value

    @property
    def signer_identity(self) -> str:
        """The exact workflow identity a certificate must carry."""
        return f"https://github.com/{self.verify_repository}/{self.workflow_path}@{self.signer_ref}"

    @property
    def signer_branch(self) -> str:
        return self.signer_ref.removeprefix("refs/heads/")
