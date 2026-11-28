"""The signer repository is pinned by id and its trusted branch must be protected.

The answers are recorded from the live GitHub API for mandate-verify (its repository id and
the rules in force on main); the decisions are the pure functions the service applies to them.
"""

import json
from pathlib import Path

import pytest

from src.configs.evidence_settings import EvidenceSettings
from src.infra_services.attestation_service import (
    REQUIRED_BRANCH_RULES,
    protection_gaps,
    repository_name_gap,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "evidence"
REPOSITORY = json.loads((FIXTURES / "signer_repository.json").read_text())
RULES = [rule["type"] for rule in json.loads((FIXTURES / "signer_branch_rules.json").read_text())]


@pytest.mark.req("REQ-108")
def test_the_recorded_signer_repository_is_the_one_at_the_pinned_id() -> None:
    settings = EvidenceSettings()
    assert REPOSITORY["id"] == settings.signer_repository_id
    assert repository_name_gap(REPOSITORY["full_name"], settings.verify_repository) is None


@pytest.mark.req("REQ-108")
def test_a_repository_that_took_over_the_id_under_another_name_is_refused() -> None:
    gap = repository_name_gap("someone-else/mandate-verify", "drivestream-lab/mandate-verify")
    assert gap is not None and "someone-else/mandate-verify" in gap


@pytest.mark.req("REQ-108")
def test_the_recorded_rules_on_main_cover_update_deletion_and_non_fast_forward() -> None:
    assert protection_gaps(RULES) == []


@pytest.mark.req("REQ-108")
@pytest.mark.parametrize("missing", REQUIRED_BRANCH_RULES)
def test_a_branch_missing_any_required_rule_is_not_protected(missing: str) -> None:
    assert protection_gaps([rule for rule in RULES if rule != missing]) == [missing]


@pytest.mark.req("REQ-108")
def test_a_branch_with_no_rules_is_not_protected() -> None:
    assert protection_gaps([]) == list(REQUIRED_BRANCH_RULES)
