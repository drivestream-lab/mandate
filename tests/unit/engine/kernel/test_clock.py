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
    """Name every system clock read or clock-module import, resolving import aliases."""
    tree = ast.parse(source)
    names: dict[str, str] = {}  # local name -> what it stands for ("datetime", "time.time", ...)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("datetime", "time"):
            for alias in node.names:
                names[alias.asname or alias.name] = (
                    alias.name if node.module == "datetime" else f"time.{alias.name}"
                )
            if node.module == "time":
                found.append("from time import")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ("datetime", "time"):
                    names[alias.asname or alias.name] = alias.name
                if alias.name == "time":
                    found.append("import time")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            owner = func.value
            owner_name = (
                owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
            )
            owner_name = names.get(owner_name, owner_name)
            if (owner_name, func.attr) in _CLOCK_CALLS:
                found.append(f"{owner_name}.{func.attr}")
        elif isinstance(func, ast.Name):
            target = names.get(func.id, "")
            if tuple(target.split(".", 1)) in _CLOCK_CALLS:
                found.append(target)
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


def test_the_scan_catches_aliased_imports() -> None:
    assert _clock_reads("from datetime import datetime as dt\nx = dt.now()\n") == ["datetime.now"]
    assert _clock_reads("from datetime import date as d\nx = d.today()\n") == ["date.today"]
    assert _clock_reads("import time as t\nx = t.time()\n") == ["import time", "time.time"]
    assert _clock_reads("from time import time as now\nx = now()\n") == [
        "from time import",
        "time.time",
    ]
    assert _clock_reads("from time import monotonic as m\nx = m()\n") == [
        "from time import",
        "time.monotonic",
    ]
    assert _clock_reads("import datetime as m\nx = m.datetime.utcnow()\n") == ["datetime.utcnow"]


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
