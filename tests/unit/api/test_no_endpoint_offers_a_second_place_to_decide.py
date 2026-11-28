"""Gates are decided on their pull request: the service exposes nothing that writes a decision."""

import pytest
from fastapi.routing import APIRoute

from src.app import create_app

_WORDS = ("decid", "signoff", "gate", "approve", "decision")


@pytest.mark.req("REQ-86")
def test_no_route_that_changes_state_is_about_deciding_a_gate() -> None:
    routes = [route for route in create_app().routes if isinstance(route, APIRoute)]
    writes = [
        route.path
        for route in routes
        if route.methods and route.methods - {"GET", "HEAD", "OPTIONS"}
    ]
    assert not [path for path in writes if any(word in path.lower() for word in _WORDS)]
