"""A scripted coder: reports a fixed change on the branch named in its brief. It calls no model.

The brief is JSON in the issue description: {"branch": "...", "task": "..."}.
"""

import sys
from typing import Any

from src.models.role_output_models import CoderResult
from tests.agents.agent_runtime import run_scripted_step


def code(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": f"Scripted change for: {brief['task']}",
        "branch": str(brief["branch"]),
        "changed_files": ["README.md"],
    }


if __name__ == "__main__":
    sys.exit(run_scripted_step(CoderResult, code))
