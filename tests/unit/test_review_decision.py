"""The hand-run review decision recorder writes ledger-format lines to a local file only."""

import json
from pathlib import Path

import pytest

from scripts.record_review_decision import append_decision, main, output_is_allowed
from src.models.review_decision_models import (
    ReviewChoiceType,
    ReviewDecisionEntry,
    ReviewVersionStamp,
)

_COMMIT = "a" * 40


def _entry() -> ReviewDecisionEntry:
    return ReviewDecisionEntry(
        actor="reviewer",
        choice=ReviewChoiceType.APPROVED,
        target_commit=_COMMIT,
        pull_request="drivestream-lab/mandate#12",
        version_stamp=ReviewVersionStamp(mandate_release="0.1.0", rules_version="v0.5.12"),
    )


@pytest.mark.req("REQ-120")
def test_decision_is_appended_as_one_json_line(tmp_path: Path) -> None:
    output = tmp_path / "decisions.jsonl"
    append_decision(_entry(), output)
    append_decision(_entry(), output)
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["entry_type"] == "decision"
    assert record["actor"] == "reviewer"
    assert record["choice"] == "approved"
    assert record["target_commit"] == _COMMIT
    assert record["version_stamp"] == {"mandate_release": "0.1.0", "rules_version": "v0.5.12"}


@pytest.mark.req("REQ-120")
def test_output_inside_mandate_meta_is_refused(tmp_path: Path) -> None:
    inside = tmp_path / "mandate-meta" / "ledger-import" / "decisions.jsonl"
    assert not output_is_allowed(inside)
    with pytest.raises(ValueError):
        append_decision(_entry(), inside)
    assert not inside.exists()


@pytest.mark.req("REQ-120")
def test_command_line_writes_the_given_file(tmp_path: Path) -> None:
    output = tmp_path / "out.jsonl"
    code = main(
        [
            "--output", str(output),
            "--actor", "reviewer",
            "--choice", "changes_requested",
            "--target-commit", _COMMIT,
            "--pull-request", "drivestream-lab/mandate#3",
            "--mandate-release", "0.1.0",
            "--rules-version", "v0.5.12",
        ]
    )  # fmt: skip
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["choice"] == "changes_requested"
