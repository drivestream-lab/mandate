"""The pure rules readiness applies to what Paperclip reports, for states a live run cannot make."""

import pytest
from pydantic import ValidationError

from src.business_services.programmes.programme_readiness_service import (
    _skill_action_denied,  # pyright: ignore[reportPrivateUsage]
    agent_unusable_cause,
)
from src.models.paperclip_models import PaperclipAgent, SkillPolicy

_AGENT = {"id": "a1", "name": "Mandate", "role": "engineer", "status": "idle"}


def _agent(**fields: str) -> PaperclipAgent:
    return PaperclipAgent.model_validate({**_AGENT, "lifecycleState": "ready", **fields})


def _policy(*rules: dict[str, object], default: str = "allow") -> SkillPolicy:
    return SkillPolicy.model_validate({"defaultEffect": default, "rules": list(rules)})


def _rule(rule_id: str, priority: int, effect: str, **subject: object) -> dict[str, object]:
    return {
        "id": rule_id,
        "priority": priority,
        "effect": effect,
        "subject": {"type": "agents", "agentIds": ["a1"], **subject},
        "actions": ["skills.create"],
    }


def test_an_agent_without_a_lifecycle_state_is_not_read() -> None:
    with pytest.raises(ValidationError):
        PaperclipAgent.model_validate(_AGENT)


@pytest.mark.parametrize("state", ["paused", "terminated", "unknown"])
def test_an_agent_that_is_not_ready_is_not_usable(state: str) -> None:
    assert agent_unusable_cause(_agent(lifecycleState=state)) is not None


def test_a_ready_idle_agent_is_usable() -> None:
    assert agent_unusable_cause(_agent()) is None


def test_a_higher_priority_allow_beats_a_deny() -> None:
    policy = _policy(_rule("deny", 5, "deny"), _rule("allow", 1, "allow"))

    assert not _skill_action_denied(policy, _agent(), "skills.create")


def test_the_deny_holds_when_it_comes_first() -> None:
    policy = _policy(_rule("deny", 0, "deny"), _rule("allow", 1, "allow"))

    assert _skill_action_denied(policy, _agent(), "skills.create")


def test_a_deny_for_another_action_does_not_cover_this_one() -> None:
    assert not _skill_action_denied(_policy(_rule("deny", 0, "deny")), _agent(), "skills.edit")
