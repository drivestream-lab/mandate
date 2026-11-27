"""Which requirements the as-built table says are built, and which of them lack a test."""

import ast
import fnmatch
import re
from pathlib import Path

NOT_BUILT_STATUS = "not started"
BUILT_STATUSES = frozenset({"implemented", "unit-tested", "live-verified"})
DEFAULT_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
_REQUIREMENT_ID = re.compile(r"REQ-\d+")
_MARKER_ARGUMENT_COUNT = 1


def built_requirements(as_built_table: str) -> list[str]:
    """Requirement ids whose row is marked implemented, unit-tested or live-verified.

    A table row is any line starting with a pipe, whatever the spacing. Raises ValueError
    naming the line when its first cell mentions a requirement id but is not exactly one, or
    when a status is blank or not one of the four known.
    """
    built: list[str] = []
    for line in as_built_table.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        requirement = cells[0]
        if not _REQUIREMENT_ID.fullmatch(requirement):
            if "REQ-" in requirement:
                raise ValueError(f"unparseable requirement row: {line!r}")
            continue
        status = cells[2] if len(cells) >= 3 else ""
        if status in BUILT_STATUSES:
            built.append(requirement)
        elif status != NOT_BUILT_STATUS:
            raise ValueError(f"{requirement}: unknown status {status!r}")
    return built


def requirements_without_test(as_built_table: str, tested: set[str]) -> list[str]:
    """Built requirements that no test carries a req marker for."""
    return [req for req in built_requirements(as_built_table) if req not in tested]


def _marker_requirement(node: ast.expr) -> str | None:
    """The id in a pytest.mark.req("REQ-nn") call, else None."""
    if not isinstance(node, ast.Call) or len(node.args) != _MARKER_ARGUMENT_COUNT:
        return None
    func = node.func
    is_req_marker = (
        isinstance(func, ast.Attribute)
        and func.attr == "req"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )
    argument = node.args[0]
    if is_req_marker and isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def _pytestmark_requirements(statement: ast.stmt) -> set[str]:
    """Ids in a `pytestmark = <marker or list of markers>` assignment."""
    if isinstance(statement, ast.Assign):
        targets = statement.targets
        value = statement.value
    elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
        targets = [statement.target]
        value = statement.value
    else:
        return set()
    if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
        return set()
    items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
    found = {_marker_requirement(item) for item in items}
    return {requirement for requirement in found if requirement is not None}


def _decorator_requirements(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> set[str]:
    found = {_marker_requirement(decorator) for decorator in node.decorator_list}
    return {requirement for requirement in found if requirement is not None}


def _scope_requirements(body: list[ast.stmt]) -> set[str]:
    """Markers that pytest applies, in a module or Test class body."""
    tested: set[str] = set()
    for statement in body:
        tested |= _pytestmark_requirements(statement)
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if statement.name.startswith("test"):
                tested |= _decorator_requirements(statement)
        elif isinstance(statement, ast.ClassDef) and statement.name.startswith("Test"):
            tested |= _decorator_requirements(statement)
            tested |= _scope_requirements(statement.body)
    return tested


def requirements_with_marker(
    tests_root: Path, file_patterns: tuple[str, ...] = DEFAULT_TEST_FILE_PATTERNS
) -> set[str]:
    """Requirement ids marked on tests pytest would collect under tests_root.

    A static scan, so journeys and other suites count without being run. Only files matching
    pytest's python_files patterns count, and only markers pytest applies: decorators of
    test* functions and Test* classes, and pytestmark assignments.
    """
    tested: set[str] = set()
    for path in tests_root.rglob("*.py"):
        if not any(fnmatch.fnmatch(path.name, pattern) for pattern in file_patterns):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tested |= _scope_requirements(tree.body)
    return tested
