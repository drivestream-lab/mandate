"""The rule readiness applies to an agent record Paperclip reports."""

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from src.business_services.programmes.programme_readiness_service import (
    agent_unusable_cause,
    scoped_allow_causes,
)
from src.models.paperclip_models import PaperclipAgent, SkillPolicy

_AGENT = {"id": "a1", "name": "Mandate", "role": "engineer", "status": "idle"}


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


def _policy(subject: Mapping[str, object], resources: dict[str, object] | None) -> SkillPolicy:
    rule = {
        "id": "scoped",
        "effect": "allow",
        "subject": subject,
        "actions": ["skills.create", "skills.read"],
        "resources": resources,
    }
    return SkillPolicy.model_validate({"defaultEffect": "deny", "rules": [rule]})


@pytest.mark.parametrize(
    "subject",
    [
        {"type": "all_agents"},
        {"type": "agents", "agentIds": ["a1"]},
        {"type": "roles", "roles": [" Engineer "]},
    ],
)
def test_an_allow_rule_limited_to_some_skills_is_named(subject: Mapping[str, object]) -> None:
    causes = scoped_allow_causes(_policy(subject, {"sourceTypes": ["managed"]}), _agent())

    assert causes == ["allow rule scoped with a resource selector covers it for skills.create"]


def test_an_unscoped_rule_or_one_for_another_agent_is_not_named_here() -> None:
    assert scoped_allow_causes(_policy({"type": "all_agents"}, None), _agent()) == []
    other = {"type": "agents", "agentIds": ["a2"]}
    assert scoped_allow_causes(_policy(other, {"sourceTypes": ["managed"]}), _agent()) == []
