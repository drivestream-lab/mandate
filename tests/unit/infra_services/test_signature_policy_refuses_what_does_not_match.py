"""A real recorded bundle (the pinned caller's run on mandate-sandbox-svc) is accepted under
the policy it was signed for, and refused once the policy differs in any one respect.

The bundle, its subject digest and the evidence tarball are recorded from a real run; the
Sigstore verifier is the real one, with its embedded trust root (offline), so nothing about
the signature is faked.

The bundle was signed by the signer workflow at refs/heads/main (mandate-verify 6e6baf2), so
it verifies under the default policy and is refused under any policy that names another ref,
workflow or repository. A signer at a tag is refused too: that policy is built with
model_construct, which skips the branch-only validation.
"""

import json
from pathlib import Path

import pytest
from sigstore.verify import Verifier

from src.configs.evidence_settings import EvidenceSettings
from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.infra_services.attestation_service import AttestationError, AttestationService
from src.models.evidence_models import EvidenceArtifact, EvidenceRefusal, EvidenceTarget

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "evidence"
RECORD = json.loads((FIXTURES / "pinned_run.json").read_text())
BUNDLE = json.loads((FIXTURES / "pinned_run_bundle.json").read_text())
OTHER_COMMIT = "b" * 40


async def _token() -> str:
    return "not used"


def _service(settings: EvidenceSettings | None = None) -> AttestationService:
    return AttestationService(
        _token, settings or EvidenceSettings(), Verifier.production(offline=True)
    )


async def _verify(
    service: AttestationService,
    *,
    digest: str = RECORD["subject_sha256"],
    repository: str = RECORD["repository"],
    commit: str = RECORD["commit"],
    signer_commit: str = RECORD["signer_commit"],
) -> None:
    await service.verify_signature(BUNDLE, digest, repository, commit, signer_commit)


@pytest.mark.req("REQ-108")
async def test_the_recorded_bundle_verifies_under_the_policy_it_was_signed_for() -> None:
    await _verify(_service())


@pytest.mark.req("REQ-108")
@pytest.mark.parametrize(
    "changed",
    [
        {"commit": OTHER_COMMIT},
        {"repository": "drivestream-lab/mandate-sandbox-meta"},
    ],
)
async def test_a_bundle_for_another_commit_or_repository_is_refused(
    changed: dict[str, str],
) -> None:
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await _verify(_service(), **changed)


@pytest.mark.req("REQ-108")
@pytest.mark.parametrize(
    "settings",
    [
        EvidenceSettings.model_construct(signer_ref="refs/tags/evidence-1"),
        EvidenceSettings(signer_ref="refs/heads/develop"),
        EvidenceSettings(workflow_path=".github/workflows/other.yml"),
        EvidenceSettings(verify_repository="drivestream-lab/mandate-sandbox-svc"),
    ],
)
async def test_a_bundle_signed_at_a_tag_or_another_branch_workflow_or_repository_is_refused(
    settings: EvidenceSettings,
) -> None:
    """A signer at refs/tags/evidence-1 or at refs/heads/develop is not the trusted main."""
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await _verify(_service(settings))


@pytest.mark.req("REQ-108")
def test_the_signer_must_be_a_branch() -> None:
    for ref in ("refs/tags/evidence-1", "main", "refs/heads/"):
        with pytest.raises(ValueError):
            EvidenceSettings.model_validate({"signer_ref": ref})
    assert EvidenceSettings().signer_ref == "refs/heads/main"


@pytest.mark.req("REQ-108")
async def test_a_run_signed_by_an_older_head_is_refused_naming_both_commits() -> None:
    now = "c" * 40
    signed = RECORD["signer_commit"]
    with pytest.raises(
        EvidenceRefusal, match=f"signed by mandate-verify {signed}, .* is now {now}"
    ):
        await _verify(_service(), signer_commit=now)


@pytest.mark.req("REQ-108")
async def test_a_bundle_whose_subject_is_not_the_downloaded_evidence_is_refused() -> None:
    with pytest.raises(EvidenceRefusal, match="attested subject"):
        await _verify(_service(), digest="0" * 64)


INVALID_BUNDLE: dict[str, object] = {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json"}
TARBALL = (FIXTURES / "pinned_run_evidence.tgz").read_bytes()
TARGET = EvidenceTarget(
    repository=RECORD["repository"],
    commit=RECORD["commit"],
    caller_workflow=".github/workflows/evidence-pinned.yml",
    test_set=("tests/unit",),
    expected_test_set_digest="1" * 64,
)
ARTIFACT = EvidenceArtifact(
    artifact_id=1, run_id=1, run_attempt=1, created_at="2026-11-28T00:00:00Z", size_bytes=1
)


class _OffersBundles(AttestationService):
    """The real service, offline, with GitHub's answers fixed; the walk stops at the tree read,
    so reaching it shows the signature step passed."""

    def __init__(self, bundles: list[dict[str, object]]) -> None:
        super().__init__(_token, EvidenceSettings(), Verifier.production(offline=True))
        self._bundles = bundles

    async def signer_head(self) -> str:
        return RECORD["signer_commit"]

    async def attestations(self, repository: str, subject_digest: str) -> list[dict[str, object]]:
        return self._bundles

    async def tree_blobs(self, repository: str, commit: str) -> dict[str, tuple[str, str]]:
        raise AttestationError("reached the tree read")


@pytest.mark.req("REQ-108")
async def test_an_invalid_bundle_is_skipped_and_the_real_one_still_verifies() -> None:
    service = EvidenceVerificationService(_OffersBundles([INVALID_BUNDLE, BUNDLE]))
    with pytest.raises(EvidenceRefusal, match="reached the tree read"):
        await service.verify_bytes(TARGET, TARBALL, ARTIFACT)


@pytest.mark.req("REQ-108")
async def test_only_invalid_bundles_are_refused_with_a_reason() -> None:
    service = EvidenceVerificationService(_OffersBundles([INVALID_BUNDLE]))
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await service.verify_bytes(TARGET, TARBALL, ARTIFACT)
