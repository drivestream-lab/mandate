"""The latest run attempt of the caller workflow decides which evidence counts.

The run and artifact listings are shaped like GitHub's; the pure selection is what is tested.
"""

import pytest

from src.infra_services.attestation_service import (
    ArtifactListing,
    RunListing,
    evidence_item,
    newest_caller_run,
)
from src.models.evidence_models import EvidenceRefusal

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
