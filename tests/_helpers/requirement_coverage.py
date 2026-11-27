"""Which requirements the as-built table says are built, and which of them lack a test."""

import ast
from pathlib import Path

NOT_BUILT_STATUS = "not started"
BUILT_STATUSES = frozenset({"implemented", "unit-tested", "live-verified"})
_ROW_PREFIX = "| REQ-"
_MARKER_ARGUMENT_COUNT = 1


def built_requirements(as_built_table: str) -> list[str]:
    """Requirement ids whose row is marked implemented, unit-tested or live-verified.

    Raises ValueError naming the row when a status is blank or not one of the four known.
    """
    built: list[str] = []
    for line in as_built_table.splitlines():
        if not line.startswith(_ROW_PREFIX):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        requirement = cells[0]
        status = cells[2] if len(cells) >= 3 else ""
        if status in BUILT_STATUSES:
            built.append(requirement)
        elif status != NOT_BUILT_STATUS:
            raise ValueError(f"{requirement}: unknown status {status!r}")
    return built


def requirements_without_test(as_built_table: str, tested: set[str]) -> list[str]:
    """Built requirements that no test carries a req marker for."""
    return [req for req in built_requirements(as_built_table) if req not in tested]


def _is_req_marker(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "req"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    )


def requirements_with_marker(tests_root: Path) -> set[str]:
    """Requirement ids named by a req marker in any test file under tests_root.

    A static scan, so journeys and other suites count without being run.
    """
    tested: set[str] = set()
    for path in tests_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_req_marker(node):
                continue
            if len(node.args) != _MARKER_ARGUMENT_COUNT:
                continue
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                tested.add(argument.value)
    return tested
