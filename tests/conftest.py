"""Run-wide pytest setup: fail the run when a built requirement has no test.

A requirement counts as built when its row in docs/specification/as-built/requirements.md is
marked implemented, unit-tested or live-verified. Each needs at least one test, anywhere under
tests/, carrying @pytest.mark.req("REQ-nn") on a test function or Test class, or in pytestmark,
in a file pytest collects (python_files); the markers are read statically, so journeys count
without being run. The check runs only with --require-req-coverage, which `make test` passes.
A missing table, or a row whose status is blank or unknown, fails the run too.
"""

from pathlib import Path

import pytest

from tests._helpers.requirement_coverage import requirements_without_test, requirements_with_marker

_AS_BUILT = Path("docs/specification/as-built/requirements.md")
_TESTS_ROOT = Path("tests")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-req-coverage",
        action="store_true",
        default=False,
        help="fail the run when a built requirement has no test carrying a req marker",
    )


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    if not config.getoption("require_req_coverage"):
        return
    table = config.rootpath / _AS_BUILT
    if not table.is_file():
        raise pytest.UsageError(f"requirement coverage check: {_AS_BUILT} is missing")
    try:
        missing = requirements_without_test(
            table.read_text(encoding="utf-8"),
            requirements_with_marker(
                config.rootpath / _TESTS_ROOT, tuple(config.getini("python_files"))
            ),
        )
    except ValueError as error:
        raise pytest.UsageError(f"requirement coverage check: {error}") from error
    if missing:
        raise pytest.UsageError(
            "built requirements with no test carrying @pytest.mark.req: " + ", ".join(missing)
        )
