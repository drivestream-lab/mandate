"""Which requirements the as-built table says are built, and which of them lack a test."""

NOT_BUILT_STATUS = "not started"
_ROW_PREFIX = "| REQ-"


def built_requirements(as_built_table: str) -> list[str]:
    """Requirement ids whose row is marked implemented, unit-tested or live-verified."""
    built: list[str] = []
    for line in as_built_table.splitlines():
        if not line.startswith(_ROW_PREFIX):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[2] and cells[2] != NOT_BUILT_STATUS:
            built.append(cells[0])
    return built


def requirements_without_test(as_built_table: str, tested: set[str]) -> list[str]:
    """Built requirements that no test carries a req marker for."""
    return [req for req in built_requirements(as_built_table) if req not in tested]
