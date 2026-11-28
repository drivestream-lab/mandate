"""Run-signed evidence: what Mandate expects of a target, what a bundle holds, what it decided."""

import re

from pydantic import BaseModel, ConfigDict, field_validator

BUNDLE_FILES = (
    "binding.json",
    "report.json",
    "environment.json",
    "junit.xml",
    "collected.txt",
    "digest-inputs.txt",
)
"""The six files of an evidence bundle, exactly; anything missing or extra is refused."""

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class EvidenceRefusal(Exception):
    """Evidence was refused; the reason says why. Refusal means the evidence counts as missing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EvidenceTarget(BaseModel):
    """What evidence must be for: a repository at a commit, with the protected test set."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str
    caller_workflow: str
    """Path of the governed repository's caller workflow, for example
    .github/workflows/verify.yml; only its runs count as the commit's runs."""
    test_set: tuple[str, ...]
    expected_test_set_digest: str
    """The protected test-set digest fixed at spec sign-off, supplied by the caller (the
    recorded spec signoff). The signed binding must carry exactly this digest."""
    quarantine: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()

    @field_validator("expected_test_set_digest")
    @classmethod
    def _signed_off_digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("the expected test-set digest must be a sha256 hex digest")
        return value

    @field_validator("commit")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if not _SHA.fullmatch(value):
            raise ValueError("commit must be 40 lowercase hex characters")
        return value

    @field_validator("repository")
    @classmethod
    def _owner_and_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("repository must be owner/name")
        return value


class EvidenceBinding(BaseModel):
    """binding.json: what the signed run says it ran."""

    model_config = ConfigDict(extra="ignore")

    repository: str
    commit: str
    caller_sha: str
    run_id: str
    run_attempt: str
    test_set: list[str]
    test_set_digest: str
    dependencies_digest: str
    tools_digest: str
    collected_digest: str
    quarantine: list[str]
    plugins: list[str]
    result: str
    artifacts: dict[str, str]

    @field_validator("test_set_digest", "dependencies_digest", "tools_digest", "collected_digest")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("not a sha256 hex digest")
        return value


class EvidenceReport(BaseModel):
    """report.json: the outcome of the protected test set."""

    model_config = ConfigDict(extra="ignore")

    result: str
    tests: int
    failures: int
    errors: int
    skipped: int
    pytest_exit_code: int
    collect_exit_code: int
    collected: int
    deselected: int


class EvidenceEnvironment(BaseModel):
    """environment.json: the environment manifest (service versions are deferred)."""

    model_config = ConfigDict(extra="ignore")

    runner_image: str
    os: str
    python: str
    packages: list[str]
    packages_sha256: str


class EvidenceBundle(BaseModel):
    """A complete, internally consistent bundle (signature not yet checked)."""

    binding: EvidenceBinding
    report: EvidenceReport
    environment: EvidenceEnvironment
    collected: tuple[str, ...]


class EvidenceArtifact(BaseModel):
    """One evidence artifact of a workflow run, the latest attempt first."""

    model_config = ConfigDict(frozen=True)

    artifact_id: int
    run_id: int
    run_attempt: int
    created_at: str
    size_bytes: int


class VerifiedEvidence(BaseModel):
    """Evidence Mandate accepts for a commit."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str
    run_id: int
    run_attempt: int
    tests: int
    test_set_digest: str
    tools_digest: str
    dependencies_digest: str
    signer_identity: str
    signer_digest: str
    """The mandate-verify commit (main's head, read live) the evidence was trusted under;
    the ledger entry for the decision carries it."""
