"""Contract tests run on the same per-run stack the journeys use (ADR-017: real systems only).

The stack fixtures live with the journeys; they are re-exported here so a run of the contract
tests alone brings up, and tears down, the same pinned Paperclip.
"""

from tests.journeys.conftest import journey_stack as journey_stack
from tests.journeys.conftest import run_namespace as run_namespace
