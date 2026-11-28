"""Evidence is accepted only when the pinned signer workflow signed it for that commit.

Real runs on mandate-sandbox-svc, real GitHub artifacts and attestations, real Sigstore
verification: the caller pinned to the signer tag is accepted, a caller that edited its own CI
and signed for itself is refused, a failing run's evidence is refused, and a truncated
evidence file is refused.
"""

import pytest

from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import AttestationService
from src.models.evidence_models import EvidenceRefusal
from tests.journeys.release_a_wave.conftest import EvidenceRun, FULL_REPO


@pytest.mark.req("REQ-60")
@pytest.mark.req("REQ-61")
@pytest.mark.req("REQ-108")
async def test_the_pinned_callers_evidence_is_accepted(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    evidence_settings: EvidenceSettings,
) -> None:
    run = evidence_runs["pinned"]
    assert run.conclusion == "success"
    verified = await evidence_service.verify(run.target)
    assert verified.commit == run.commit
    assert verified.repository == FULL_REPO
    assert verified.tests > 0
    assert verified.signer_identity == evidence_settings.signer_identity


@pytest.mark.req("REQ-108")
async def test_an_edited_callers_own_signature_is_refused(
    evidence_runs: dict[str, EvidenceRun], evidence_service: EvidenceVerificationService
) -> None:
    run = evidence_runs["edited"]
    assert run.conclusion == "success"
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify(run.target)
    assert "Sigstore verification failed" in refused.value.reason


@pytest.mark.req("REQ-61")
async def test_evidence_of_a_failing_run_is_refused(
    evidence_runs: dict[str, EvidenceRun], evidence_service: EvidenceVerificationService
) -> None:
    run = evidence_runs["failing"]
    assert "failure" in run.conclusion
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify(run.target)
    assert "did not pass" in refused.value.reason


@pytest.mark.req("REQ-62")
async def test_truncated_evidence_counts_as_missing(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    attestations: AttestationService,
) -> None:
    run = evidence_runs["pinned"]
    artifact = await attestations.latest_evidence(FULL_REPO, run.commit)
    assert artifact is not None
    whole = await attestations.download_evidence(FULL_REPO, artifact)
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify_bytes(run.target, whole[: len(whole) // 2], artifact)
    assert "no attestation" in refused.value.reason


@pytest.mark.req("REQ-61")
async def test_evidence_for_another_commit_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    attestations: AttestationService,
) -> None:
    pinned, edited = evidence_runs["pinned"], evidence_runs["edited"]
    artifact = await attestations.latest_evidence(FULL_REPO, pinned.commit)
    assert artifact is not None
    whole = await attestations.download_evidence(FULL_REPO, artifact)
    with pytest.raises(EvidenceRefusal):
        await evidence_service.verify_bytes(edited.target, whole, artifact)
