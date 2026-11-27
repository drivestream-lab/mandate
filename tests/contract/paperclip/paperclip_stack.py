"""Set up Mandate's identity in the run's Paperclip, the way an operator would.

A board user is created and made first admin (the only way into a fresh authenticated
instance), then a company, a project, Mandate's own agent with reduced permissions, and an
ordinary second agent that Mandate must not be able to assign work to.
"""

import secrets
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict


class _Id(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str


class _Token(BaseModel):
    model_config = ConfigDict(extra="ignore")

    token: str


@dataclass(frozen=True)
class MandateIdentity:
    """Everything a test needs to act as Mandate in one provisioned Paperclip."""

    base_url: str
    company_id: str
    project_id: str
    agent_id: str
    other_agent_id: str
    other_token_file: Path
    token_file: Path
    board_user_id: str
    board_email: str
    board_password: str = field(repr=False)


_ALL_SKILL_ACTIONS = [
    "skills.create",
    "skills.import",
    "skills.install",
    "skills.edit",
    "skills.update",
    "skills.test",
    "skills.reset",
    "skills.remove",
]


_PROVISIONED: dict[str, MandateIdentity] = {}


def provision_once(base_url: str, token_file: Path) -> MandateIdentity:
    """The identity for this Paperclip, provisioned on first use: a fresh instance can be claimed once."""
    if base_url not in _PROVISIONED:
        _PROVISIONED[base_url] = provision_mandate_identity(base_url, token_file)
    return _PROVISIONED[base_url]


def provision_mandate_identity(base_url: str, token_file: Path) -> MandateIdentity:
    """Create the company, project and agents, restrict Mandate's agent, and write its token."""
    headers = {"Origin": base_url}
    password = secrets.token_hex(16)
    board_email = "board@contract.test"
    with httpx.Client(base_url=base_url, headers=headers, timeout=60) as board:
        signed_up = board.post(
            "/api/auth/sign-up/email",
            json={"email": board_email, "password": password, "name": "Board"},
        ).raise_for_status()
        board_user_id = _Id.model_validate(signed_up.json()["user"]).id
        board.post("/api/bootstrap/claim", json={}).raise_for_status()

        company_id = _post_id(board, "/api/companies", {"name": "Mandate contract"})
        project_id = _post_id(
            board, f"/api/companies/{company_id}/projects", {"name": "Mandate work"}
        )
        agent_id = _post_id(board, f"/api/companies/{company_id}/agents", _agent("Mandate"))
        other_id = _post_id(board, f"/api/companies/{company_id}/agents", _agent("Other"))

        # The three permissions Mandate must not hold, one lever each (see the contract test):
        # hiring agents, assigning work to agents, and authoring skills.
        board.patch(
            f"/api/agents/{agent_id}/permissions",
            json={"canCreateAgents": False, "canCreateSkills": False, "canAssignTasks": False},
        ).raise_for_status()
        board.patch(
            f"/api/agents/{agent_id}/interaction-permissions",
            json={"canAssignTasksToAgents": False, "canConfigureOtherAgents": False},
        ).raise_for_status()
        board.put(
            f"/api/companies/{company_id}/skill-policy",
            json={
                "schemaVersion": 1,
                "defaultEffect": "allow",
                "expectedRevision": 0,
                "rules": [
                    {
                        "id": "mandate-authors-no-skills",
                        "priority": 0,
                        "effect": "deny",
                        "subject": {"type": "agents", "agentIds": [agent_id]},
                        "actions": _ALL_SKILL_ACTIONS,
                    }
                ],
            },
        ).raise_for_status()

        key = board.post(
            f"/api/agents/{agent_id}/keys", json={"name": "mandate"}
        ).raise_for_status()
        token_file.write_text(_Token.model_validate(key.json()).token, encoding="utf-8")
        token_file.chmod(0o600)
        other_key = board.post(f"/api/agents/{other_id}/keys", json={"name": "other"})
        other_token_file = token_file.with_name("other-token")
        other_token_file.write_text(
            _Token.model_validate(other_key.raise_for_status().json()).token, encoding="utf-8"
        )
        other_token_file.chmod(0o600)

    return MandateIdentity(
        base_url=base_url,
        company_id=company_id,
        project_id=project_id,
        agent_id=agent_id,
        other_agent_id=other_id,
        other_token_file=other_token_file,
        token_file=token_file,
        board_user_id=board_user_id,
        board_email=board_email,
        board_password=password,
    )


def _agent(name: str) -> dict[str, object]:
    return {
        "name": name,
        "role": "engineer",
        "title": name,
        "adapterType": "process",
        "adapterConfig": {"command": "true"},
    }


def _post_id(client: httpx.Client, path: str, body: dict[str, object]) -> str:
    return _Id.model_validate_json(client.post(path, json=body).raise_for_status().content).id
