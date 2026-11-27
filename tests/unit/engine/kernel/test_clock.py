"""Time comes from an injectable clock; nothing in engine reads the system clock."""

import ast
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.engine.kernel.clock import Clock, utc_now
from src.infra_services.system_clock_service import SystemClockService

_ENGINE = Path(__file__).resolve().parents[4] / "src" / "engine"
_CLOCK_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("date", "today"),
    ("time", "time"),
    ("time", "time_ns"),
    ("time", "monotonic"),
    ("time", "perf_counter"),
}


class _Fixed:
    def __init__(self, reading: datetime) -> None:
        self._reading = reading

    def now(self) -> datetime:
        return self._reading


def _clock_reads(source: str) -> list[str]:
    """Name every system clock read or clock-module import in the source."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            owner_name = (
                owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
            )
            if (owner_name, node.func.attr) in _CLOCK_CALLS:
                found.append(f"{owner_name}.{node.func.attr}")
        if isinstance(node, ast.ImportFrom) and node.module == "time":
            found.append("from time import")
        if isinstance(node, ast.Import) and any(alias.name == "time" for alias in node.names):
            found.append("import time")
    return found


@pytest.mark.req("REQ-54")
def test_engine_code_never_reads_the_system_clock() -> None:
    offenders = {
        str(path.relative_to(_ENGINE)): reads
        for path in _ENGINE.rglob("*.py")
        if (reads := _clock_reads(path.read_text()))
    }
    assert offenders == {}


def test_the_scan_catches_a_clock_read() -> None:
    assert _clock_reads("from datetime import datetime\nx = datetime.now()\n") == ["datetime.now"]
    assert _clock_reads("import time\nx = time.time()\n") == ["import time", "time.time"]
    assert _clock_reads("import datetime\nx = datetime.datetime.utcnow()\n") == ["datetime.utcnow"]


def test_an_injected_clock_supplies_the_time() -> None:
    fixed = datetime(2026, 11, 27, 9, 30, tzinfo=UTC)
    clock: Clock = _Fixed(fixed)
    assert utc_now(clock) == fixed


def test_a_naive_reading_is_rejected() -> None:
    with pytest.raises(ValueError):
        utc_now(_Fixed(datetime(2026, 11, 27, 9, 30)))


def test_a_non_utc_reading_is_rejected() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    with pytest.raises(ValueError):
        utc_now(_Fixed(datetime(2026, 11, 27, 9, 30, tzinfo=ist)))


def test_the_system_clock_is_a_clock_reading_utc() -> None:
    clock: Clock = SystemClockService()
    assert utc_now(clock).tzinfo is not None
