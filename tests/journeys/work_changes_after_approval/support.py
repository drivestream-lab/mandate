"""Helpers for reading what Mandate recorded when a signoff was voided."""

import httpx

from src.models.gate_models import PullRequestRef
from src.models.ledger_models import DecisionRecord, LedgerEntryType, RungType
from src.models.signoff_models import MANDATE_ACTOR, GateRule
from tests.journeys.sign_a_gate.conftest import OWNER, SIGNER_LOGIN
from tests.journeys.sign_a_gate.support import Services


async def voids_recorded(services: Services, role: str) -> list[DecisionRecord]:
    """Every void Mandate recorded under this role, oldest first (a correction counts as one)."""
    async with services.postgres.get_session() as session:
        entries = await services.repository.read_all(session)
    found: list[DecisionRecord] = []
    for entry in entries:
        if entry.entry_type == LedgerEntryType.DECISION:
            record = DecisionRecord.model_validate(entry.payload)
            if record.actor == MANDATE_ACTOR and record.role == role:
                found.append(record)
    return found


def remove_label(token: str, ref: PullRequestRef, label: str) -> None:
    """Someone other than Mandate takes a label off a pull request."""
    httpx.delete(
        f"https://api.github.com/repos/{OWNER}/{ref.repo}/issues/{ref.number}/labels/{label}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30,
    ).raise_for_status()


WAVE_RULE = GateRule(
    label="wave-accepted", branch="develop", rung=RungType.L2, holders=frozenset({SIGNER_LOGIN})
)
"""The wave gate as the sandbox configures it: its own label, and its own -revised and -stale."""


def edit_review_body(token: str, ref: PullRequestRef, review_id: int, body: str) -> None:
    """Someone other than the reviewer rewrites a review's body (GitHub allows it)."""
    httpx.put(
        f"https://api.github.com/repos/{OWNER}/{ref.repo}/pulls/{ref.number}/reviews/{review_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": body},
        timeout=30,
    ).raise_for_status()
