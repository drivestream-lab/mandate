"""Run-wide pytest setup: fail the run when a built requirement has no test.

A requirement counts as built when its row in docs/specification/as-built/requirements.md is
marked implemented, unit-tested or live-verified. Each needs at least one test carrying
@pytest.mark.req("REQ-nn"). The check runs on whole-suite runs only, not on a single file,
test id, -k or -m selection.
"""

from pathlib import Path

import pytest

from tests._helpers.requirement_coverage import requirements_without_test

_AS_BUILT = Path("docs/specification/as-built/requirements.md")


def _is_whole_suite_run(config: pytest.Config) -> bool:
    selected = config.getoption("keyword") or config.getoption("markexpr")
    return not selected and all(Path(arg).is_dir() for arg in config.args)


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    table = config.rootpath / _AS_BUILT
    if not _is_whole_suite_run(config) or not table.is_file():
        return
    tested = {
        str(marker.args[0])
        for item in session.items
        for marker in item.iter_markers(name="req")
        if marker.args
    }
    missing = requirements_without_test(table.read_text(encoding="utf-8"), tested)
    if missing:
        raise pytest.UsageError(
            "built requirements with no test carrying @pytest.mark.req: " + ", ".join(missing)
        )
