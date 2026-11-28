"""The toy PRD names, in its signed text, what the wave's evidence must match."""

from pathlib import Path

import pytest
import yaml

from src.business_services.runner.walking_skeleton_runner_service import EVIDENCE_BLOCK
from src.models.evidence_models import WaveEvidenceSpec

_PRD = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "walking_skeleton" / "toy_prd.md"
)


@pytest.mark.req("REQ-108")
def test_the_evidence_block_of_the_toy_prd_reads_as_a_wave_evidence_spec() -> None:
    text = (
        _PRD.read_text(encoding="utf-8")
        .replace("__CALLER_WORKFLOW__", ".github/workflows/walking-skeleton-run.yml")
        .replace("__TEST_SET_DIGEST__", "a" * 64)
    )
    found = EVIDENCE_BLOCK.search(text)
    assert found is not None
    spec = WaveEvidenceSpec.model_validate(yaml.safe_load(found.group("body")))
    assert spec.repository == "drivestream-lab/mandate-sandbox-svc"
    assert spec.test_set == ("tests/unit",) and spec.expected_test_set_digest == "a" * 64


@pytest.mark.req("REQ-108")
def test_a_prd_without_an_evidence_block_names_nothing() -> None:
    assert EVIDENCE_BLOCK.search("# a PRD\n\nno block here\n") is None
