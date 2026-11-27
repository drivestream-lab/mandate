"""The rule readiness applies to an agent record Paperclip reports."""

import pytest
from pydantic import ValidationError

from src.business_services.programmes.programme_readiness_service import (
    agent_unusable_cause,
)
from src.models.paperclip_models import PaperclipAgent

_AGENT = {"id": "a1", "name": "Mandate", "status": "idle"}


def _agent(**fields: str) -> PaperclipAgent:
    return PaperclipAgent.model_validate({**_AGENT, "lifecycleState": "ready", **fields})


def test_an_agent_without_a_lifecycle_state_is_not_read() -> None:
    with pytest.raises(ValidationError):
        PaperclipAgent.model_validate(_AGENT)


@pytest.mark.parametrize("state", ["paused", "terminated", "unknown"])
def test_an_agent_that_is_not_ready_is_not_usable(state: str) -> None:
    assert agent_unusable_cause(_agent(lifecycleState=state)) is not None


def test_a_ready_idle_agent_is_usable() -> None:
    assert agent_unusable_cause(_agent()) is None
