"""Judges merges into governed branches and the state of their rulesets. Pure: no IO, no clock.

A merge is guarded when the required check had passed, posted by Mandate's App, on the head that
was merged, before it was merged. A merge that was not is a policy breach, except an emergency
merge by a named human on one of Mandate's own repositories, which is the recorded exception.

The gate rulesets and branch protection are judged by state, not by who changed them: each is
reduced to a digest of its canonical form and compared with the baseline the caller supplies
(what a decided Launchpad run applied). An empty or missing baseline is a finding in itself.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import JsonValue

from src.models.sweep_models import (
    GovernanceFinding,
    HeadStatus,
    MergeObservation,
    MergeVerdictType,
    RepoBaseline,
)

PASSING_STATE = "success"
RULESET_FIELDS = ("rules", "conditions", "enforcement", "target")
"""What of a ruleset counts: its rules, conditions, enforcement and target. A ruleset answer
without one of them is unreadable, never null."""

BYPASS_LIMIT = (
    "bypass actors are outside Mandate's view: GitHub shows them only to callers who can edit "
    "rulesets, which Mandate must not be, so a change to them is not detected (KD's control)"
)

_VOLATILE_KEYS = frozenset({"updated_at", "created_at", "node_id", "_links"})
"""Fields that change without the ruleset changing: times, node ids and links (any key named
url or ending in _url is dropped too). The ruleset's own id is kept in the baseline."""


def walk_complete(current: str | None, checkpoint: str | None, steps: int, max_depth: int) -> bool:
    """True when the first-parent walk should stop: it reached the checkpoint or ran out of
    parents, or, only for a first sweep that has no checkpoint, went `max_depth` landings back.

    Once a checkpoint exists the walk goes all the way to it, however many landings came in."""
    if current is None or current == checkpoint:
        return True
    return checkpoint is None and steps >= max_depth


def seed_allowed(existing_checkpoint: str | None) -> bool:
    """A checkpoint can only be seeded where there is none; a sweep alone moves it afterwards."""
    return existing_checkpoint is None


def checkpoint_reached(last: str | None, checkpoint: str | None) -> bool:
    """A later sweep must end its walk at the checkpoint; anything else means the branch's own
    line no longer leads to it (a rewrite) or more landings than the depth allows."""
    return checkpoint is None or last == checkpoint


def revert_due(revertable: bool, revert_recorded: bool) -> bool:
    """A breach is answered only once its revert pull request exists: open one when the merge
    can be reverted and none is on record."""
    return revertable and not revert_recorded


def passing_check(statuses: Sequence[HeadStatus], merged_at: datetime, mandate_login: str) -> bool:
    """True when the newest check status at or before the merge was a success from Mandate's App.

    Several statuses at the same instant all have to be passing: a failure at that instant wins.
    """
    before = [item for item in statuses if item.created_at <= merged_at]
    if not before:
        return False
    newest = max(item.created_at for item in before)
    latest = [item for item in before if item.created_at == newest]
    return all(item.state == PASSING_STATE and item.creator == mandate_login for item in latest)


def judge_merge(
    observation: MergeObservation,
    mandate_login: str,
    own_repos: frozenset[str],
    emergency_humans: frozenset[str],
) -> MergeVerdictType:
    """Guarded, a breach, or the emergency exception.

    A landing that is not a merged pull request's merge commit is a breach whatever statuses it
    has: GitHub's merged-by login is the only authenticated merger there is, so the exception is
    only for a merged pull request, on one of Mandate's own repositories, merged by a named human.
    """
    if observation.pull_number is None:
        return MergeVerdictType.BREACH
    if passing_check(observation.statuses, observation.merged_at, mandate_login):
        return MergeVerdictType.GUARDED
    if (
        observation.repo in own_repos
        and observation.merged_by is not None
        and observation.merged_by in emergency_humans
    ):
        return MergeVerdictType.EMERGENCY_EXCEPTION
    return MergeVerdictType.BREACH


def breach_reason(observation: MergeObservation) -> str:
    """Why a merge is a breach, naming the commit, the head and who merged it."""
    if observation.pull_number is None:
        return (
            f"{observation.repo}: {observation.merge_commit} landed on {observation.branch} "
            f"at {observation.merged_at.isoformat()} but is not a merged pull request's merge commit"
        )
    who = observation.merged_by or "an unknown account"
    return (
        f"{observation.repo}: {observation.merge_commit} merged into {observation.branch} by {who} "
        f"at {observation.merged_at.isoformat()} although head {observation.head_sha} had no "
        "passing mandate/gate-decision"
    )


def emergency_reason(observation: MergeObservation) -> str:
    """The emergency exception's evidence: who, which commit, when."""
    return (
        f"{observation.repo}: emergency merge of {observation.merge_commit} into "
        f"{observation.branch} by {observation.merged_by} at {observation.merged_at.isoformat()}; "
        f"head {observation.head_sha} had no passing mandate/gate-decision"
    )


def _strip(value: JsonValue) -> JsonValue:
    """Drop volatile and link fields at every depth."""
    if isinstance(value, dict):
        return {
            key: _strip(item)
            for key, item in value.items()
            if key not in _VOLATILE_KEYS and key != "url" and not key.endswith("_url")
        }
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def canonical_json(value: JsonValue) -> str:
    """Keys sorted at every depth, no spaces, volatile and link fields removed."""
    return json.dumps(_strip(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sorted_list(value: JsonValue) -> JsonValue:
    """A list whose order carries no meaning, in canonical order."""
    if isinstance(value, list):
        return sorted(value, key=canonical_json)
    return value


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unreadable_ruleset(ruleset: Mapping[str, JsonValue]) -> str | None:
    """The name of a field a ruleset answer lacks, or None. A missing field is never null."""
    for name in RULESET_FIELDS:
        if name not in ruleset:
            return name
    return None


def ruleset_digest(ruleset: Mapping[str, JsonValue]) -> str:
    """SHA-256 of a ruleset's rules, conditions, enforcement and target in canonical form. Rules
    are unordered, so they are sorted first. Bypass actors are not part of it: GitHub does not
    show them to Mandate. A ruleset lacking a field must be refused with `unreadable_ruleset`."""
    chosen: dict[str, JsonValue] = {}
    for name in RULESET_FIELDS:
        value = ruleset[name]
        chosen[name] = _sorted_list(value) if name == "rules" else value
    return _digest(canonical_json(chosen))


def protection_digest(protection: JsonValue) -> str | None:
    """SHA-256 of a branch's protection in canonical form; None when the branch has none."""
    if protection is None:
        return None
    return _digest(canonical_json(protection))


def governance_findings(
    repo: str,
    rulesets_now: Mapping[int, str],
    protections_now: Mapping[str, str | None],
    baseline: RepoBaseline | None,
) -> tuple[GovernanceFinding, ...]:
    """Every difference between what the repository has and what it is allowed to have.

    No baseline, or one that lists neither a ruleset nor a branch protection, is a finding:
    there is nothing to compare against, which is never a pass.
    """
    if baseline is None or not (baseline.rulesets or baseline.protections):
        return (
            GovernanceFinding(
                repo=repo,
                subject="baseline",
                reason="no baseline of gate rulesets and branch protection is on record",
            ),
        )
    found: list[GovernanceFinding] = []
    allowed = {item.ruleset_id: item.digest for item in baseline.rulesets}
    for ruleset_id, digest in sorted(rulesets_now.items()):
        subject = f"ruleset {ruleset_id}"
        if ruleset_id not in allowed:
            found.append(
                GovernanceFinding(
                    repo=repo,
                    subject=f"{subject} added@{digest[:12]}",
                    reason=f"{subject} is not in the baseline",
                )
            )
        elif allowed[ruleset_id] != digest:
            found.append(
                GovernanceFinding(
                    repo=repo,
                    subject=f"{subject} changed@{digest[:12]}",
                    reason=f"{subject} differs from the baseline",
                )
            )
    for ruleset_id in sorted(set(allowed) - set(rulesets_now)):
        found.append(
            GovernanceFinding(
                repo=repo,
                subject=f"ruleset {ruleset_id} missing",
                reason=f"ruleset {ruleset_id} is in the baseline but no longer exists",
            )
        )
    expected = {item.branch: item.digest for item in baseline.protections}
    for branch, digest in sorted(protections_now.items()):
        subject = f"protection {branch}"
        state = (digest or "none")[:12]
        if branch not in expected:
            found.append(
                GovernanceFinding(
                    repo=repo,
                    subject=f"{subject} added@{state}",
                    reason=f"the protection of {branch} is not in the baseline",
                )
            )
        elif expected[branch] != digest:
            found.append(
                GovernanceFinding(
                    repo=repo,
                    subject=f"{subject} changed@{state}",
                    reason=f"the protection of {branch} differs from the baseline",
                )
            )
    return tuple(found)
