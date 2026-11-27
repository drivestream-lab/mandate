"""The brief text: what it states, and which gates carry the deciding role's call."""

from uuid import UUID

import pytest

from src.engine.gates.brief import call_digest, render_brief, shows_deciding_role_call
from src.models.gate_models import BriefOption, GateBrief, GateClassType
from src.models.ledger_models import EvidenceReference
from src.models.role_output_models import DecidingRoleCall

_HEAD = "a" * 40
_GATE = UUID("00000000-0000-0000-0000-000000000001")
_CALL = DecidingRoleCall(
    option="hold",
    reasons=("the rollout plan has no rollback step",),
    evidence_cited=("role-note-77",),
)


def _brief(gate_class: GateClassType) -> GateBrief:
    return GateBrief(
        gate_class=gate_class,
        title="Gate: add a retry to delivery",
        what_is_decided="Whether delivery retries failed sends",
        options=(
            BriefOption(option_id="ship", description="Add the retry", impact="Fewer lost sends"),
            BriefOption(option_id="hold", description="Leave it", impact="Sends can be lost"),
        ),
        recommendation="ship",
        recommendation_reason="Lost sends cost more than a retry",
        head_sha=_HEAD,
        evidence=(EvidenceReference(kind="ci", reference="run 12", digest="b" * 64),),
        after_signoff="The retry merges and the next wave starts",
    )


@pytest.mark.req("REQ-39")
def test_brief_states_the_decision_options_recommendation_evidence_and_what_follows() -> None:
    body = render_brief(_brief(GateClassType.INTENT), None)

    for part in (
        "Whether delivery retries failed sends",
        "Add the retry",
        "Impact: Fewer lost sends",
        "Recommended: **ship**. Lost sends cost more than a retry",
        f"head `{_HEAD}`",
        "run 12",
        "The retry merges and the next wave starts",
    ):
        assert part in body


@pytest.mark.req("REQ-103")
@pytest.mark.parametrize("gate_class", [GateClassType.INTENT, GateClassType.DESIGN])
def test_intent_and_design_briefs_are_the_same_with_or_without_a_call(
    gate_class: GateClassType,
) -> None:
    brief = _brief(gate_class)

    with_call = render_brief(brief, _CALL)

    assert with_call == render_brief(brief, None)
    assert "role-note-77" not in with_call
    assert "rollback" not in with_call
    assert not shows_deciding_role_call(gate_class)


@pytest.mark.req("REQ-103")
@pytest.mark.parametrize("gate_class", [GateClassType.VERIFICATION, GateClassType.HOUSEKEEPING])
def test_verification_and_housekeeping_briefs_show_the_call_with_its_evidence(
    gate_class: GateClassType,
) -> None:
    body = render_brief(_brief(gate_class), _CALL)

    assert shows_deciding_role_call(gate_class)
    assert "Option: **hold**" in body
    assert "the rollout plan has no rollback step" in body
    assert "role-note-77" in body


@pytest.mark.req("REQ-103")
def test_call_digest_changes_with_the_nonce_and_the_gate() -> None:
    other_gate = UUID("00000000-0000-0000-0000-000000000002")
    digest = call_digest(_GATE, _CALL, "n" * 32)

    assert digest == call_digest(_GATE, _CALL, "n" * 32)
    assert digest != call_digest(_GATE, _CALL, "m" * 32)
    assert digest != call_digest(other_gate, _CALL, "n" * 32)
