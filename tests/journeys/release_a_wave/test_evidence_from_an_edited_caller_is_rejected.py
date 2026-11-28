"""Evidence is accepted only when the pinned signer workflow signed it for that commit.

Real runs on mandate-sandbox-svc, real GitHub artifacts and attestations, real Sigstore
verification: the caller pinned to the signer tag is accepted, a caller that edited its own CI
and signed for itself is refused, a failing run's evidence is refused, a truncated evidence file
is refused, a validly signed run over an edited protected test is refused (its test set is not
the one fixed at sign-off), and a signer tag that no longer points at the pinned commit is
refused.
"""

import pytest

from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import AttestationService
from src.models.evidence_models import EvidenceRefusal
from tests.journeys.release_a_wave.conftest import FULL_REPO, EvidenceRun

OTHER_COMMIT = "d3b3d4f52447d4048aee034e0fc65d7d1d8e887c"
"""A real mandate-verify commit that the signer tag does not point at."""


@pytest.mark.req("REQ-60")
@pytest.mark.req("REQ-61")
@pytest.mark.req("REQ-108")
async def test_the_pinned_callers_evidence_is_accepted(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    evidence_settings: EvidenceSettings,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["pinned"]
    assert run.conclusion == "success"
    verified = await evidence_service.verify(run.target(signed_off_digest))
    assert verified.commit == run.commit
    assert verified.repository == FULL_REPO
    assert verified.tests > 0
    assert verified.test_set_digest == signed_off_digest
    assert verified.signer_identity == evidence_settings.signer_identity
    assert verified.signer_digest == evidence_settings.signer_commit


@pytest.mark.req("REQ-108")
async def test_an_edited_callers_own_signature_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["edited"]
    assert run.conclusion == "success"
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify(run.target(signed_off_digest))
    assert "Sigstore verification failed" in refused.value.reason


@pytest.mark.req("REQ-108")
async def test_a_signed_run_over_an_edited_protected_test_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["tampered"]
    assert run.conclusion == "success"
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify(run.target(signed_off_digest))
    assert "fixed at spec sign-off" in refused.value.reason


@pytest.mark.req("REQ-108")
async def test_a_signer_tag_that_moved_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    attestations: AttestationService,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["pinned"]
    moved = AttestationService(
        attestations._token_provider,  # pyright: ignore[reportPrivateUsage]
        EvidenceSettings(signer_commit=OTHER_COMMIT),
    )
    await moved.initialize()
    try:
        with pytest.raises(EvidenceRefusal) as refused:
            await EvidenceVerificationService(moved).verify(run.target(signed_off_digest))
    finally:
        await moved.close()
    assert "tag moved" in refused.value.reason


@pytest.mark.req("REQ-61")
async def test_evidence_of_a_failing_run_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["failing"]
    assert "failure" in run.conclusion
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify(run.target(signed_off_digest))
    assert "ended failure" in refused.value.reason


@pytest.mark.req("REQ-62")
async def test_truncated_evidence_counts_as_missing(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    attestations: AttestationService,
    signed_off_digest: str,
) -> None:
    run = evidence_runs["pinned"]
    artifact = await attestations.latest_evidence(FULL_REPO, run.commit, run.workflow)
    whole = await attestations.download_evidence(FULL_REPO, artifact)
    with pytest.raises(EvidenceRefusal) as refused:
        await evidence_service.verify_bytes(
            run.target(signed_off_digest), whole[: len(whole) // 2], artifact
        )
    assert "no attestation" in refused.value.reason


@pytest.mark.req("REQ-61")
async def test_evidence_for_another_commit_is_refused(
    evidence_runs: dict[str, EvidenceRun],
    evidence_service: EvidenceVerificationService,
    attestations: AttestationService,
    signed_off_digest: str,
) -> None:
    pinned, edited = evidence_runs["pinned"], evidence_runs["edited"]
    artifact = await attestations.latest_evidence(FULL_REPO, pinned.commit, pinned.workflow)
    whole = await attestations.download_evidence(FULL_REPO, artifact)
    with pytest.raises(EvidenceRefusal):
        await evidence_service.verify_bytes(edited.target(signed_off_digest), whole, artifact)
