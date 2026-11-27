"""A scripted deciding role: picks from the brief's options by a fixed rule and cites evidence.

It calls no model. The brief is JSON in the issue description: {"options": [...], "evidence":
[...]}. The call is the first option, with the evidence the brief carries. A brief that asks for
`"fault": "omit_evidence"` makes the script build a call without evidence, so the schema check
fails and the call counts as missing.
"""

import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.role_output_models import DecidingRoleCall
from tests.agents.agent_runtime import run_scripted_step


class DecidingBrief(BaseModel):
    """What the issue description carries for a deciding role."""

    model_config = ConfigDict(extra="forbid")

    options: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[str, ...]
    fault: Literal["omit_evidence"] | None = None


def decide(brief: DecidingBrief) -> dict[str, object]:
    first = brief.options[0]
    evidence = () if brief.fault == "omit_evidence" else brief.evidence
    return {
        "option": first,
        "reasons": [
            f"{first} is first of {len(brief.options)} options and the evidence supports it"
        ],
        "evidence_cited": list(evidence),
    }


if __name__ == "__main__":
    sys.exit(run_scripted_step(DecidingBrief, DecidingRoleCall, decide))
