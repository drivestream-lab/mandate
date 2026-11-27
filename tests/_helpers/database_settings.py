"""Reads the database settings a real-Postgres test needs from the environment."""

import os

import pytest


def setting(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default or "")
    if not value:
        pytest.fail(f"{name} is not set; see this file's docstring for the settings it needs")
    return value
