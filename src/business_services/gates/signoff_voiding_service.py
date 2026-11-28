"""Voids a signoff when its head moved or an upstream pull request changed, and says so.

The ledger decides: a void is an entry Mandate writes (choice "voided"), once per gate, head and
cause, and the check reads it back. The -revised and -stale labels are shown for people and are
never read to decide anything; anyone may apply or remove them. Mandate applies one when it
records the void, and removes both once the holder's signoff on the current head passes.
This service reads GitHub and the ledger and writes the ledger and labels; it never signs.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from injector import inject

from src.business_services.base_business_service import BaseBusinessService
from src.business_services.gates.signoff_service import SIGNOFF_CHOICE, PullRequestReader
from src.business_services.ledger.ledger_append_service import LedgerAppendService
from src.engine.gates.voiding_rules import (
    attested_upstream_heads,
    changed_upstreams,
    heads_newest_first,
    latest_time,
    recorded_no_failure_reason,
    revised_cause,
    revised_label,
    revised_role,
    signoff_follows_void,
    stale_cause,
    stale_failure_reason,
    stale_label,
    stale_role,
    earlier_approves,
    unresolved_no,
    upstream_evidence,
    void_failure_reason,
)
from src.models.gate_models import PullRequestRef
from src.models.kernel_models import VersionStamp
from src.models.ledger_models import DecisionOption, DecisionRecord, EvidenceReference
from src.models.signoff_models import (
    MANDATE_ACTOR,
    DecisionLink,
    GateRule,
    PullRequestSnapshot,
    SignoffReading,
    UpstreamHead,
)

_WORKFLOW_VERSION = "gate-voiding/1"
_RULES_VERSION = "mandate-rules"


class LabelClient(Protocol):
    """What voiding needs from GitHub besides reading."""

    async def add_label(self, ref: PullRequestRef, label: str) -> None: ...

    async def remove_label(self, ref: PullRequestRef, label: str) -> None: ...


class SignoffVoidingService(BaseBusinessService):
    """Records voids and labels them; reads recorded no's on linked artifacts."""

    @inject
    def __init__(self, ledger: LedgerAppendService) -> None:
        super().__init__()
        self._ledger = ledger

    async def void_superseded_signoff(
        self,
        github: LabelClient,
        snapshot: PullRequestSnapshot,
        rule: GateRule,
        stamp: VersionStamp,
    ) -> bool:
        """Record the void of a signoff the ledger holds for an earlier head, and label the pull request.

        True when there is one. Each signoff voided by each new head is recorded once, so a head
        that returns after being signed and voided again is voided again.
        """
        for earlier in earlier_approves(snapshot, rule):
            recorded = await self._ledger.latest_choice(
                earlier.reviewer, rule.label, earlier.head_sha
            )
            if recorded != SIGNOFF_CHOICE:
                continue
            await self._record(
                rule,
                revised_role(rule),
                earlier.head_sha,
                revised_cause(earlier, snapshot.head_sha),
                (f"{earlier.reviewer}'s recorded signoff on {earlier.head_sha} no longer holds",),
                (),
                stamp,
            )
            await self._label(github, snapshot, revised_label(rule))
            return True
        return False

    async def stale_failure(
        self,
        github: LabelClient,
        snapshot: PullRequestSnapshot,
        signoff: SignoffReading,
        rule: GateRule,
        upstream_now: Sequence[UpstreamHead],
        stamp: VersionStamp,
    ) -> str | None:
        """The reason this signoff is stale, or None. Records the void when it is first seen.

        The baseline is what the holder attested: a linked upstream pull request that the
        attestation does not name, or names at another head, is stale.
        """
        changed = changed_upstreams(attested_upstream_heads(signoff.attestation), upstream_now)
        if not changed:
            return None
        await self._record(
            rule,
            stale_role(rule),
            snapshot.head_sha,
            stale_cause(changed, signoff.signed_at),
            (f"an upstream change after {signoff.signer} reviewed against it",),
            upstream_evidence(changed),
            stamp,
        )
        await self._label(github, snapshot, stale_label(rule))
        return stale_failure_reason(stale_label(rule))

    async def void_failure(
        self, snapshot: PullRequestSnapshot, signoff: SignoffReading, rule: GateRule
    ) -> str | None:
        """The reason a void on this head still stands, or None.

        A head carrying a revised or stale void needs a signoff given after the void, even when
        the head is a commit that was signed before.
        """
        head = snapshot.head_sha
        times: list[datetime | None] = []
        for role in (revised_role(rule), stale_role(rule)):
            record = await self._ledger.latest_decision_record(MANDATE_ACTOR, role, head)
            times.append(None if record is None else record.decided_at)
        if signoff_follows_void(signoff.signed_at, latest_time(times)):
            return None
        return void_failure_reason(revised_label(rule))

    async def clear_labels(
        self, github: LabelClient, snapshot: PullRequestSnapshot, rule: GateRule
    ) -> None:
        """Remove -revised and -stale once the signoff on the current head has passed."""
        for label in (revised_label(rule), stale_label(rule)):
            if label in snapshot.labels:
                await github.remove_label(snapshot.ref, label)

    async def unresolved_no_failure(
        self,
        github: PullRequestReader,
        downstream: PullRequestRef,
        links: Sequence[DecisionLink],
    ) -> str | None:
        """The reason a linked decision's recorded no blocks this merge, or None.

        Only the holder of that decision, in that decision's own role, counts.
        """
        for link in links:
            if link.downstream != downstream:
                continue
            artifact = await github.read_pull_request(link.artifact)
            choices = [
                await self._ledger.latest_choice(link.holder, link.decision_role, head)
                for head in heads_newest_first(artifact)
            ]
            if unresolved_no(choices):
                return recorded_no_failure_reason(link.artifact, link.holder)
        return None

    async def _record(
        self,
        rule: GateRule,
        role: str,
        target_head: str,
        cause: str,
        reasons: tuple[str, ...],
        evidence: tuple[EvidenceReference, ...],
        stamp: VersionStamp,
    ) -> None:
        """Write a void once per cause; a new cause on the same gate and head is a correction."""
        record = DecisionRecord(
            actor=MANDATE_ACTOR,
            role=role,
            rung=rule.rung,
            options_offered=(
                DecisionOption(option_id=cause, description="The signoff no longer counts"),
            ),
            choice=cause,
            reasons=reasons,
            evidence=evidence,
            target_version=target_head,
            workflow_version=_WORKFLOW_VERSION,
            model_version=_RULES_VERSION,
            decided_at=datetime.now(UTC),
        )
        await self._ledger.record_decision_once(record, stamp, "another cause voided it")

    async def _label(self, github: LabelClient, snapshot: PullRequestSnapshot, label: str) -> None:
        if label not in snapshot.labels:
            await github.add_label(snapshot.ref, label)
