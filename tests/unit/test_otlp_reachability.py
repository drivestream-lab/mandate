"""The OTLP reachability check and the reload/workers settings."""

import socket

import pytest
from pydantic import ValidationError

from src.configs.app_settings import AppSettings
from src.utils.otlp_reachability import collector_address, warn_if_collector_unreachable


def test_collector_address_reads_host_and_port():
    assert collector_address("http://otel-collector:4318") == ("otel-collector", 4318)
    assert collector_address("http://collector") == ("collector", 4318)


def test_collector_address_is_none_when_empty():
    assert collector_address("  ") is None


def test_unreachable_collector_is_reported_not_raised():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert warn_if_collector_unreachable(f"http://127.0.0.1:{port}", timeout=0.5) is False


def test_listening_collector_is_reachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        assert warn_if_collector_unreachable(f"http://127.0.0.1:{s.getsockname()[1]}") is True


def test_reload_is_off_by_default():
    assert AppSettings().reload is False


def test_reload_with_many_workers_is_refused():
    with pytest.raises(ValidationError):
        AppSettings(reload=True, workers=2)
