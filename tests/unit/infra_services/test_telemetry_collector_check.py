"""The OTLP reachability check and the reload/workers settings."""

import socket
from types import SimpleNamespace

import pytest
from loguru import logger
from pydantic import ValidationError

from src.configs.app_settings import AppSettings
from src.infra_services.telemetry_service import TelemetryService, collector_address


def test_collector_address_reads_host_and_port():
    assert collector_address("http://otel-collector:4318") == ("otel-collector", 4318)
    assert collector_address("http://collector") == ("collector", 4318)


def test_collector_address_is_none_when_empty():
    assert collector_address("  ") is None


@pytest.mark.parametrize("endpoint", ["http://collector:abc", "http://collector:99999"])
def test_collector_address_is_none_for_a_bad_port(endpoint: str):
    assert collector_address(endpoint) is None


def _service(endpoint: str) -> TelemetryService:
    service = TelemetryService.__new__(TelemetryService)
    service._settings = SimpleNamespace(exporter_otlp_endpoint=endpoint)  # type: ignore[assignment]
    return service


@pytest.mark.parametrize("endpoint", ["", "http://collector:abc", "http://collector:99999"])
def test_unusable_endpoint_warns_and_does_not_raise(endpoint: str):
    assert _service(endpoint).warn_if_collector_unreachable() is False


def test_endpoint_credentials_are_not_logged():
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        _service("http://user:secrettoken@127.0.0.1:1").warn_if_collector_unreachable(timeout=0.5)
    finally:
        logger.remove(sink)
    assert messages and not any("secrettoken" in m for m in messages)


def test_unreachable_collector_is_reported_not_raised():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert _service(f"http://127.0.0.1:{port}").warn_if_collector_unreachable(timeout=0.5) is False


def test_listening_collector_is_reachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert (
            _service(f"http://127.0.0.1:{s.getsockname()[1]}").warn_if_collector_unreachable()
            is True
        )


def test_reload_is_off_by_default():
    assert AppSettings().reload is False


def test_reload_with_many_workers_is_refused():
    with pytest.raises(ValidationError):
        AppSettings(reload=True, workers=2)
