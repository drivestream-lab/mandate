"""A scripted deciding role: picks from the brief's options by a fixed rule and cites evidence.

It calls no model. The brief is JSON in the issue description: {"options": [...], "evidence":
[...]}. The call is the first option, with the evidence the brief carries. A brief that asks for
`"fault": "omit_evidence"` makes the script build a call without evidence, so the schema check
fails and the call counts as missing.
"""

import sys
from typing import Any

from src.models.role_output_models import DecidingRoleCall
from tests.agents.agent_runtime import run_scripted_step


def decide(brief: dict[str, Any]) -> dict[str, Any]:
    options = [str(option) for option in brief["options"]]
    omit = brief.get("fault") == "omit_evidence"
    evidence = [] if omit else [str(item) for item in brief["evidence"]]
    return {
        "option": options[0],
        "reasons": [
            f"{options[0]} is first of {len(options)} options and the evidence supports it"
        ],
        "evidence_cited": evidence,
    }


if __name__ == "__main__":
    sys.exit(run_scripted_step(DecidingRoleCall, decide))
