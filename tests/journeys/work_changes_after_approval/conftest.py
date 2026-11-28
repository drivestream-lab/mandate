"""Fixtures for the journeys where work changes after a signoff: the sign-a-gate ones, reused."""

from tests.journeys.sign_a_gate.conftest import (
    agent_host,
    app_postgres,
    author_token,
    board_user,
    desk,
    github_app,
    mandate_identity,
    mandate_token,
    paperclip,
    sandbox_desk,
    signer_token,
    throwaway_database,
)

__all__ = [
    "agent_host",
    "app_postgres",
    "author_token",
    "board_user",
    "desk",
    "github_app",
    "mandate_identity",
    "mandate_token",
    "paperclip",
    "sandbox_desk",
    "signer_token",
    "throwaway_database",
]
