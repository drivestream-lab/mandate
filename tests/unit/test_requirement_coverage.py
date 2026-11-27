"""A requirement marked built must have a test; one not started need not."""

from tests._helpers.requirement_coverage import built_requirements, requirements_without_test

_TABLE = """| Requirement | Wave | Status | Evidence |
| --- | --- | --- | --- |
| REQ-01 | W1 | not started | |
| REQ-02 | W1 | implemented | PR 3 |
| REQ-03 | W2 | unit-tested | PR 4 |
| REQ-04 | W2 | live-verified | PR 5 |
"""


def test_only_rows_past_not_started_count_as_built() -> None:
    assert built_requirements(_TABLE) == ["REQ-02", "REQ-03", "REQ-04"]


def test_built_requirement_without_a_marker_is_named() -> None:
    assert requirements_without_test(_TABLE, {"REQ-02", "REQ-04"}) == ["REQ-03"]


def test_nothing_missing_when_every_built_requirement_has_a_test() -> None:
    assert requirements_without_test(_TABLE, {"REQ-02", "REQ-03", "REQ-04"}) == []
