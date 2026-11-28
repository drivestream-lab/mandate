"""A real recorded bundle (the pinned caller's run on mandate-sandbox-svc) is accepted under
the policy it was signed for, and refused once the policy differs in any one respect.

The bundle, its subject digest and the evidence tarball are recorded from a real run; the
Sigstore verifier is the real one, with its embedded trust root (offline), so nothing about
the signature is faked.

The bundle was signed by the signer workflow at refs/tags/evidence-1, so it stands for "a
signer at another ref" under the trusted-branch policy; the control that it verifies when the
policy names that ref is built with model_construct, which skips the branch-only validation.
"""

import json
from pathlib import Path

import pytest
from sigstore.verify import Verifier

from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import AttestationService
from src.models.evidence_models import EvidenceRefusal

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "evidence"
RECORD = json.loads((FIXTURES / "pinned_run.json").read_text())
BUNDLE = json.loads((FIXTURES / "pinned_run_bundle.json").read_text())
OTHER_COMMIT = "b" * 40


async def _token() -> str:
    return "not used"


SIGNED_AT_TAG = EvidenceSettings.model_construct(signer_ref=RECORD["signer_ref"])
"""Settings naming the ref the recorded bundle was really signed at."""


def _service(settings: EvidenceSettings | None = None) -> AttestationService:
    return AttestationService(_token, settings or SIGNED_AT_TAG, Verifier.production(offline=True))


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
        {},
        {"signer_ref": "refs/heads/develop"},
        {"signer_ref": "refs/heads/main", "workflow_path": ".github/workflows/other.yml"},
        {"verify_repository": "drivestream-lab/mandate-sandbox-svc"},
    ],
)
async def test_a_bundle_signed_at_a_tag_or_another_branch_workflow_or_repository_is_refused(
    settings: dict[str, str],
) -> None:
    """The default trusted ref is main: a signer at refs/tags/evidence-1 or at
    refs/heads/develop is refused."""
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await _verify(_service(EvidenceSettings.model_validate(settings)))


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
