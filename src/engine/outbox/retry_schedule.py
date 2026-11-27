"""When a failed outbox delivery is tried again: pure rules, no IO and no clock."""

from datetime import timedelta

BASE_DELAY = timedelta(seconds=5)
MAX_DELAY = timedelta(minutes=15)


def retry_delay(failed_attempts: int) -> timedelta:
    """The wait after the given number of failed attempts: doubles each time, up to a cap."""
    if failed_attempts < 1:
        raise ValueError("a retry delay needs at least one failed attempt")
    # Cap the exponent first so a long run of failures cannot build a huge integer.
    doublings = min(failed_attempts - 1, 20)
    return min(BASE_DELAY * (2**doublings), MAX_DELAY)
