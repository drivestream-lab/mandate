"""A scripted coder: reports a fixed change on the branch named in its brief. It calls no model.

The brief is JSON in the issue description: {"branch": "...", "task": "..."}.
"""

import sys
from pydantic import BaseModel, ConfigDict, Field

from src.models.role_output_models import CoderResult
from tests.agents.agent_runtime import run_scripted_step


class CoderBrief(BaseModel):
    """What the issue description carries for a coder."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    branch: str = Field(min_length=1)


def code(brief: CoderBrief) -> dict[str, object]:
    return {
        "summary": f"Scripted change for: {brief.task}",
        "branch": brief.branch,
        "changed_files": ["README.md"],
    }


if __name__ == "__main__":
    sys.exit(run_scripted_step(CoderBrief, CoderResult, code))
