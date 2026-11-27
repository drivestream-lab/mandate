"""The wait between delivery attempts: pure rule, no database."""

from datetime import timedelta

import pytest

from src.engine.outbox.retry_schedule import BASE_DELAY, MAX_DELAY, retry_delay


@pytest.mark.req("REQ-55")
def test_the_wait_doubles_with_each_failure_then_stops_at_the_cap() -> None:
    assert retry_delay(1) == BASE_DELAY
    assert retry_delay(2) == BASE_DELAY * 2
    assert retry_delay(3) == BASE_DELAY * 4
    assert retry_delay(50) == MAX_DELAY
    assert retry_delay(10_000) == MAX_DELAY


@pytest.mark.req("REQ-55")
def test_no_failure_has_no_wait() -> None:
    with pytest.raises(ValueError):
        retry_delay(0)
    assert retry_delay(1) > timedelta(0)
