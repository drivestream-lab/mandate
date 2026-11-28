"""A real recorded bundle (the pinned caller's run on mandate-sandbox-svc) is accepted under
the policy it was signed for, and refused once the policy differs in any one respect.

The bundle, its subject digest and the evidence tarball are recorded from a real run; the
Sigstore verifier is the real one, with its embedded trust root (offline), so nothing about
the signature is faked.
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
        {"signer_commit": OTHER_COMMIT},
    ],
)
async def test_a_bundle_for_another_commit_repository_or_signer_digest_is_refused(
    changed: dict[str, str],
) -> None:
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await _verify(_service(), **changed)


@pytest.mark.req("REQ-108")
@pytest.mark.parametrize(
    "settings",
    [
        {"signer_ref": "refs/tags/evidence-2"},
        {"signer_ref": "refs/tags/preflight-1"},
        {"workflow_path": ".github/workflows/other.yml"},
        {"verify_repository": "drivestream-lab/mandate-sandbox-svc"},
    ],
)
async def test_a_bundle_signed_at_another_ref_workflow_or_repository_is_refused(
    settings: dict[str, str],
) -> None:
    with pytest.raises(EvidenceRefusal, match="Sigstore verification failed"):
        await _verify(_service(EvidenceSettings.model_validate(settings)))


@pytest.mark.req("REQ-108")
async def test_a_bundle_whose_subject_is_not_the_downloaded_evidence_is_refused() -> None:
    with pytest.raises(EvidenceRefusal, match="attested subject"):
        await _verify(_service(), digest="0" * 64)
