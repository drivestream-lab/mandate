"""The gate brief as text, and the digest that seals a deciding role's call.

Pure: no IO and no clock. The rule that matters: at an intent or design gate the brief is
built from the gate's content alone, so the deciding role's call cannot reach it. At the other
gates the call is shown after the author's recommendation, with the evidence it cites.
"""

import hashlib
import json
from uuid import UUID

from src.models.gate_models import BLIND_FIRST_GATES, GateBrief, GateClassType
from src.models.role_output_models import DecidingRoleCall

_SEAL_SCHEME = "mandate.sealed-call.v1"


def shows_deciding_role_call(gate_class: GateClassType) -> bool:
    """True when the brief at this kind of gate carries the deciding role's call."""
    return gate_class not in BLIND_FIRST_GATES


def call_digest(gate_id: UUID, call: DecidingRoleCall, nonce: str) -> str:
    """Hex SHA-256 over the gate, the call and a nonce, so a short option cannot be guessed."""
    canonical = json.dumps(
        [_SEAL_SCHEME, str(gate_id), call.model_dump(mode="json"), nonce],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def render_brief(brief: GateBrief, call: DecidingRoleCall | None) -> str:
    """The Markdown body posted on the gate's pull request."""
    lines = [
        f"## {brief.title}",
        "",
        f"Head commit: `{brief.head_sha}`",
        "",
        "### What is decided",
        brief.what_is_decided,
        "",
        "### Options",
    ]
    for option in brief.options:
        lines.append(f"- **{option.option_id}**: {option.description}")
        lines.append(f"  - Impact: {option.impact}")
    lines += [
        "",
        "### Recommendation",
        f"Recommended: **{brief.recommendation}**. {brief.recommendation_reason}",
        "",
        "### Evidence",
        *_evidence_lines(brief),
    ]
    if call is not None and shows_deciding_role_call(brief.gate_class):
        lines += [
            "",
            "### Deciding role's recommendation",
            f"Option: **{call.option}**",
            *[f"- {reason}" for reason in call.reasons],
            "Evidence cited:",
            *[f"- {cited}" for cited in call.evidence_cited],
        ]
    lines += ["", "### After signoff", brief.after_signoff]
    return "\n".join(lines) + "\n"


def _evidence_lines(brief: GateBrief) -> list[str]:
    if not brief.evidence:
        return [f"None recorded for `{brief.head_sha}`."]
    return [
        f"- {item.kind}: {item.reference} (sha256 `{item.digest}`, head `{brief.head_sha}`)"
        for item in brief.evidence
    ]
