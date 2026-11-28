"""Startup check that the OTLP collector can be reached.

Telemetry is not on the gate path: the service starts whatever the answer, and this only
says once, clearly, when export will not work.
"""

import socket
from urllib.parse import urlparse

from src.logging import get_logger

logger = get_logger()


def collector_address(endpoint: str) -> tuple[str, int] | None:
    """Host and port of an OTLP http endpoint, or None when it is empty or has no host."""
    if not endpoint.strip():
        return None
    parsed = urlparse(endpoint.strip())
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 4318)


def warn_if_collector_unreachable(endpoint: str, timeout: float = 2.0) -> bool:
    """Log one warning when telemetry cannot be exported; return True when it can."""
    address = collector_address(endpoint)
    if address is None:
        logger.warning(
            "Telemetry export is off: OTEL_EXPORTER_OTLP_ENDPOINT is empty or has no host"
        )
        return False
    try:
        with socket.create_connection(address, timeout=timeout):
            return True
    except OSError as error:
        logger.warning(
            "Telemetry collector is unreachable; the service runs without exported telemetry",
            endpoint=endpoint,
            error=str(error),
        )
        return False
