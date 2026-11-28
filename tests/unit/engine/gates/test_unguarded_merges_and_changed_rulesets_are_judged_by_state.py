"""A merge is guarded only by a passing check from Mandate's App before it; rulesets are judged by digest."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from src.engine.gates.unguarded_merge_rules import (
    canonical_json,
    governance_findings,
    judge_merge,
    revert_due,
    unreadable_ruleset,
    walk_complete,
    checkpoint_reached,
    passing_check,
    protection_digest,
    ruleset_digest,
)
from src.models.sweep_models import (
    HeadStatus,
    MergeObservation,
    MergeVerdictType,
    ProtectionBaseline,
    RepoBaseline,
    RulesetBaseline,
)

_T = datetime(2026, 11, 28, 10, 0, tzinfo=UTC)
_APP = "mandate-test[bot]"
_SHA = "a" * 40


def _status(
    state: str, who: str | None = _APP, at: datetime = _T - timedelta(minutes=1)
) -> HeadStatus:
    return HeadStatus(state=state, creator=who, created_at=at)


def _merge(
    statuses: tuple[HeadStatus, ...], repo: str = "r", by: str | None = "someone"
) -> MergeObservation:
    return MergeObservation(
        repo=repo,
        branch="develop",
        merge_commit=_SHA,
        head_sha="b" * 40,
        merged_by=by,
        merged_at=_T,
        pull_number=3,
        node_id="PR_x",
        statuses=statuses,
    )


@pytest.mark.req("REQ-122")
def test_a_merge_after_a_passing_check_from_the_app_is_guarded() -> None:
    verdict = judge_merge(_merge((_status("success"),)), _APP, frozenset(), frozenset())
    assert verdict is MergeVerdictType.GUARDED


@pytest.mark.req("REQ-122")
@pytest.mark.parametrize(
    "statuses",
    [
        (),
        (_status("failure"),),
        (_status("success", who="someone-else"),),
        (_status("success", who=None),),
        (_status("success", at=_T + timedelta(minutes=1)),),
        (_status("success", at=_T - timedelta(minutes=5)), _status("failure")),
        (_status("success"), _status("failure")),
    ],
)
def test_no_passing_check_before_the_merge_is_a_breach(statuses: tuple[HeadStatus, ...]) -> None:
    assert passing_check(statuses, _T, _APP) is False
    verdict = judge_merge(_merge(statuses), _APP, frozenset({"r"}), frozenset())
    assert verdict is MergeVerdictType.BREACH


@pytest.mark.req("REQ-109")
@pytest.mark.req("REQ-122")
def test_a_named_human_on_mandates_own_repo_is_the_exception_and_nowhere_else() -> None:
    own, humans = frozenset({"r"}), frozenset({"kd"})
    assert (
        judge_merge(_merge((), by="kd"), _APP, own, humans) is MergeVerdictType.EMERGENCY_EXCEPTION
    )
    assert judge_merge(_merge((), by="someone"), _APP, own, humans) is MergeVerdictType.BREACH
    assert (
        judge_merge(_merge((), repo="other", by="kd"), _APP, own, humans) is MergeVerdictType.BREACH
    )
    assert judge_merge(_merge((), by=None), _APP, own, humans) is MergeVerdictType.BREACH


@pytest.mark.req("REQ-122")
def test_the_digest_ignores_volatile_fields_and_order_but_not_content() -> None:
    base: dict[str, JsonValue] = {
        "id": 1,
        "updated_at": "t1",
        "node_id": "n1",
        "_links": {"self": {"href": "x"}},
        "enforcement": "active",
        "target": "branch",
        "conditions": {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}},
        "bypass_actors": [
            {"actor_id": 2, "actor_type": "Team"},
            {"actor_id": 1, "actor_type": "Team"},
        ],
        "rules": [{"type": "pull_request"}, {"type": "required_status_checks"}],
    }
    actors: list[JsonValue] = [
        {"actor_id": 1, "actor_type": "Team"},
        {"actor_id": 2, "actor_type": "Team"},
    ]
    rules: list[JsonValue] = [{"type": "pull_request"}, {"type": "required_status_checks"}]
    same: dict[str, JsonValue] = {
        **base,
        "updated_at": "t2",
        "node_id": "n2",
        "_links": {},
        "bypass_actors": actors,
        "rules": list(reversed(rules)),
    }
    assert ruleset_digest(base) == ruleset_digest(same)
    assert ruleset_digest(base) != ruleset_digest({**base, "enforcement": "disabled"})
    # Bypass actors are not shown to Mandate's App, so they are outside the digest.
    assert ruleset_digest(base) == ruleset_digest({**base, "bypass_actors": []})
    assert (
        canonical_json({"b": 1, "a": {"url": "u", "d": 1, "c": 2}}) == '{"a":{"c":2,"d":1},"b":1}'
    )
    assert protection_digest(None) is None
    assert protection_digest({"url": "a", "x": 1}) == protection_digest({"url": "b", "x": 1})


def _baseline(
    rulesets: tuple[RulesetBaseline, ...], protections: tuple[ProtectionBaseline, ...]
) -> RepoBaseline:
    return RepoBaseline(repo="r", rulesets=rulesets, protections=protections)


_D1, _D2 = "1" * 64, "2" * 64


@pytest.mark.req("REQ-122")
def test_a_missing_or_empty_baseline_is_a_finding_never_a_pass() -> None:
    assert [f.subject for f in governance_findings("r", {1: _D1}, {}, None)] == ["baseline"]
    empty = _baseline((), ())
    assert [f.subject for f in governance_findings("r", {}, {"develop": None}, empty)] == [
        "baseline"
    ]


@pytest.mark.req("REQ-122")
def test_a_changed_added_or_removed_ruleset_or_protection_is_a_finding() -> None:
    baseline = _baseline(
        (RulesetBaseline(ruleset_id=1, digest=_D1),),
        (
            ProtectionBaseline(branch="develop", digest=_D1),
            ProtectionBaseline(branch="main", digest=None),
        ),
    )
    assert governance_findings("r", {1: _D1}, {"develop": _D1, "main": None}, baseline) == ()
    reasons = [
        f.reason
        for f in governance_findings("r", {1: _D2, 2: _D2}, {"develop": _D2, "main": _D1}, baseline)
    ]
    assert len(reasons) == 4
    assert any("ruleset 1 differs" in r for r in reasons)
    assert any("ruleset 2 is not in the baseline" in r for r in reasons)
    assert any("protection of develop differs" in r for r in reasons)
    assert any("protection of main differs" in r for r in reasons)
    gone = governance_findings("r", {}, {"develop": _D1, "main": None}, baseline)
    assert [f.reason for f in gone] == ["ruleset 1 is in the baseline but no longer exists"]
    unlisted = governance_findings(
        "r", {1: _D1}, {"develop": _D1, "main": None, "release": _D1}, baseline
    )
    assert [f.subject.split("@")[0] for f in unlisted] == ["protection release added"]


@pytest.mark.req("REQ-122")
def test_a_ruleset_answer_lacking_a_field_is_unreadable_not_null() -> None:
    whole: dict[str, JsonValue] = {
        "rules": [],
        "conditions": None,
        "enforcement": "active",
        "target": "branch",
    }
    assert unreadable_ruleset(whole) is None
    without = {k: v for k, v in whole.items() if k != "conditions"}
    assert unreadable_ruleset(without) == "conditions"
    assert unreadable_ruleset({}) == "rules"


@pytest.mark.req("REQ-122")
def test_a_landing_that_is_not_a_merged_pull_request_is_a_breach_even_for_a_named_human() -> None:
    push = MergeObservation(
        repo="r",
        branch="develop",
        merge_commit=_SHA,
        head_sha=_SHA,
        merged_by="kd",
        merged_at=_T,
        pull_number=None,
        node_id=None,
        statuses=(_status("success"),),
    )
    verdict = judge_merge(push, _APP, frozenset({"r"}), frozenset({"kd"}))
    assert verdict is MergeVerdictType.BREACH


@pytest.mark.req("REQ-122")
def test_the_walk_stops_on_the_checkpoint_or_at_the_depth_and_only_the_checkpoint_counts() -> None:
    assert walk_complete("a", "a", 0, 5) and walk_complete(None, "a", 0, 5)
    assert walk_complete("b", "a", 5, 5) and not walk_complete("b", "a", 4, 5)
    assert checkpoint_reached("a", "a") and checkpoint_reached("zzz", None)
    assert not checkpoint_reached("b", "a") and not checkpoint_reached(None, "a")


@pytest.mark.req("REQ-122")
def test_a_breach_is_handled_only_once_its_revert_is_on_record() -> None:
    assert revert_due(revertable=True, revert_recorded=False) is True
    assert revert_due(revertable=True, revert_recorded=True) is False
    assert revert_due(revertable=False, revert_recorded=False) is False
