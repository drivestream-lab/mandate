"""A requirement marked built must have a test; one not started need not."""

from pathlib import Path

import pytest

from tests._helpers.requirement_coverage import (
    built_requirements,
    requirements_without_test,
    requirements_with_marker,
)

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


def test_blank_or_unknown_status_is_refused_naming_the_row() -> None:
    for status in ("", "Not started", "done"):
        table = f"| REQ-07 | W1 | {status} | |\n"
        with pytest.raises(ValueError, match="REQ-07"):
            built_requirements(table)


def test_marker_in_any_test_directory_counts(tmp_path: Path) -> None:
    (tmp_path / "journeys").mkdir()
    (tmp_path / "journeys" / "test_flow.py").write_text(
        'import pytest\n\n\n@pytest.mark.req("REQ-04")\ndef test_flow() -> None: ...\n',
        encoding="utf-8",
    )
    (tmp_path / "test_module_level.py").write_text(
        'import pytest\n\npytestmark = pytest.mark.req("REQ-02")\n', encoding="utf-8"
    )
    assert requirements_with_marker(tmp_path) == {"REQ-02", "REQ-04"}
    assert requirements_without_test(_TABLE, requirements_with_marker(tmp_path)) == ["REQ-03"]


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_markers_that_are_not_on_collected_tests_do_not_count(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "_helpers/test_helper.py",
        'import pytest\n\n\ndef _helper() -> None:\n    pytest.mark.req("REQ-01")\n',
    )
    _write(
        tmp_path,
        "verify/test_verify.py",
        'import pytest\n\n\n@pytest.mark.req("REQ-02")\ndef check_something() -> None: ...\n',
    )
    _write(
        tmp_path,
        "unit/notes_stray.py",
        'import pytest\n\nif False:\n    _ = pytest.mark.req("REQ-03")\n\n\n'
        '@pytest.mark.req("REQ-03")\ndef test_not_collected() -> None: ...\n',
    )
    _write(
        tmp_path,
        "unit/test_nested.py",
        'import pytest\n\nif False:\n    pytestmark = pytest.mark.req("REQ-04")\n',
    )
    assert requirements_with_marker(tmp_path) == set()


def test_markers_on_collected_tests_count(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "journeys/test_x.py",
        'import pytest\n\n\n@pytest.mark.req("REQ-01")\nasync def test_flow() -> None: ...\n',
    )
    _write(
        tmp_path,
        "unit/flow_test.py",
        'import pytest\n\n\n@pytest.mark.req("REQ-02")\nclass TestFlow:\n'
        "    def test_it(self) -> None: ...\n",
    )
    _write(
        tmp_path,
        "unit/test_marks.py",
        'import pytest\n\npytestmark = [pytest.mark.req("REQ-03"), pytest.mark.slow]\n',
    )
    assert requirements_with_marker(tmp_path) == {"REQ-01", "REQ-02", "REQ-03"}


def test_requirement_row_spacing_does_not_hide_a_row() -> None:
    for line in ("|REQ-120 |W1|implemented||", " | REQ-120 | W1 | implemented | |"):
        assert built_requirements(line) == ["REQ-120"]


def test_row_that_mentions_a_requirement_but_cannot_be_parsed_fails() -> None:
    for line in ("| REQ-120a | W1 | implemented | |", "| see REQ-120 | W1 | implemented | |"):
        with pytest.raises(ValueError, match="unparseable"):
            built_requirements(line)
    with pytest.raises(ValueError, match="REQ-120"):
        built_requirements("|REQ-120 |")
