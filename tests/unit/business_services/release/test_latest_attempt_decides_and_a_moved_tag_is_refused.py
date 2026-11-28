"""The latest run attempt of the caller workflow decides, and a moved signer tag is refused.

The run and artifact listings are shaped like GitHub's; the pure selection and the refusal
before any signature work are what is tested.
"""

import pytest

from src.business_services.release.evidence_verification_service import (
    EvidenceVerificationService,
)
from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import (
    ArtifactListing,
    AttestationService,
    RunListing,
    evidence_item,
    newest_caller_run,
)
from src.models.evidence_models import EvidenceArtifact, EvidenceRefusal, EvidenceTarget

COMMIT = "a" * 40
WORKFLOW = ".github/workflows/verify.yml"


def _run(run_id: int, attempt: int, started: str, conclusion: str | None = "success") -> RunListing:
    return RunListing(
        id=run_id,
        run_attempt=attempt,
        path=WORKFLOW,
        status="completed" if conclusion else "in_progress",
        conclusion=conclusion,
        created_at=started,
        run_started_at=started,
    )


def _artifact(attempt: int) -> ArtifactListing:
    return ArtifactListing(
        id=attempt,
        name=f"evidence-{COMMIT}-{attempt}",
        expired=False,
        created_at="2026-11-28T00:00:00Z",
        size_in_bytes=100,
    )


@pytest.mark.req("REQ-61")
def test_a_passing_first_attempt_does_not_stand_in_for_a_failed_second_attempt() -> None:
    attempt_one_only = [_artifact(1)]
    run = _run(7, 2, "2026-11-28T01:00:00Z", conclusion="failure")
    with pytest.raises(EvidenceRefusal, match="ended failure"):
        newest_caller_run([run], WORKFLOW)
    finished = _run(7, 2, "2026-11-28T01:00:00Z")
    with pytest.raises(EvidenceRefusal, match="produced no evidence"):
        evidence_item(attempt_one_only, COMMIT, finished)


@pytest.mark.req("REQ-61")
def test_the_newest_run_decides_and_must_have_finished() -> None:
    older = _run(6, 1, "2026-11-28T00:00:00Z")
    newer = _run(7, 1, "2026-11-28T02:00:00Z")
    assert newest_caller_run([older, newer], WORKFLOW).id == 7
    running = _run(8, 1, "2026-11-28T03:00:00Z", conclusion=None)
    with pytest.raises(EvidenceRefusal, match="has not finished"):
        newest_caller_run([older, newer, running], WORKFLOW)
    with pytest.raises(EvidenceRefusal, match="no run of"):
        newest_caller_run([older], ".github/workflows/other.yml")


@pytest.mark.req("REQ-61")
def test_evidence_must_be_for_exactly_the_latest_attempt() -> None:
    run = _run(7, 2, "2026-11-28T01:00:00Z")
    assert evidence_item([_artifact(1), _artifact(2)], COMMIT, run).id == 2


class _MovedTag(AttestationService):
    """The real service with only the live tag read answered by a fixed value."""

    async def live_tag_commit(self) -> str:
        return "c" * 40


async def _token() -> str:
    return "not used"


@pytest.mark.req("REQ-108")
async def test_a_signer_tag_that_no_longer_points_at_the_pinned_commit_is_refused() -> None:
    service = EvidenceVerificationService(_MovedTag(_token, EvidenceSettings()))
    target = EvidenceTarget(
        repository="o/r",
        commit=COMMIT,
        caller_workflow=WORKFLOW,
        test_set=("tests/unit",),
        expected_test_set_digest="1" * 64,
    )
    artifact = EvidenceArtifact(
        artifact_id=1, run_id=7, run_attempt=1, created_at="x", size_bytes=1
    )
    with pytest.raises(EvidenceRefusal, match="evidence-1 tag moved"):
        await service.verify_bytes(target, b"anything", artifact)
