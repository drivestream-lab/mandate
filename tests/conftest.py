"""Run-wide pytest setup: fail the run when a built requirement has no test.

A requirement counts as built when its row in docs/specification/as-built/requirements.md is
marked implemented, unit-tested or live-verified. Each needs at least one test carrying
@pytest.mark.req("REQ-nn"). The check runs only when asked for with --require-req-coverage,
which `make test` passes (the suite those tests live in). Other runs, such as `make journeys`,
do not collect the unit tests and so never apply it.
"""

from pathlib import Path

import pytest

from tests._helpers.requirement_coverage import requirements_without_test

_AS_BUILT = Path("docs/specification/as-built/requirements.md")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-req-coverage",
        action="store_true",
        default=False,
        help="fail the run when a built requirement has no test carrying a req marker",
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    table = config.rootpath / _AS_BUILT
    if not config.getoption("require_req_coverage") or not table.is_file():
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
