"""What a scripted agent needs from Paperclip's process adapter, using only the standard library.

The adapter starts the script with the run's identity in its environment (PAPERCLIP_API_URL,
PAPERCLIP_RUN_ID, PAPERCLIP_API_KEY) and no task. The script finds its task by asking Paperclip
which issue the run belongs to, does its fixed work, posts the result as a comment on that issue,
closes the issue, and prints the same result on stdout. The script never prints its key.
"""

import json
import os
import sys
import urllib.request
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.models.role_output_models import RoleOutput


class _Reading(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _RunRecord(_Reading):
    issue_id: str = Field(alias="issueId")


class _IssueRecord(_Reading):
    description: str


_BRIEF_ERROR = 2
_SCHEMA_ERROR = 3


def _call(method: str, path: str, body: dict[str, object] | None = None) -> bytes:
    base = os.environ.get("PAPERCLIP_API_URL") or os.environ["PAPERCLIP_RUNTIME_API_URL"]
    request = urllib.request.Request(
        base.rstrip("/") + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['PAPERCLIP_API_KEY']}",
            "Content-Type": "application/json",
            "X-Paperclip-Run-Id": os.environ["PAPERCLIP_RUN_ID"],
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def run_scripted_step[B: BaseModel, M: RoleOutput](
    brief_model: type[B], model: type[M], work: Callable[[B], dict[str, object]]
) -> int:
    """Read the brief on this run's issue, build the output, check it, and hand it back.

    The issue description is JSON and must fit `brief_model`; `work` turns it into the output's
    fields. An output that does not fit `model` is not posted and the script exits non-zero: it
    counts as missing.
    """
    run = _RunRecord.model_validate_json(
        _call("GET", f"/api/heartbeat-runs/{os.environ['PAPERCLIP_RUN_ID']}")
    )
    issue = _IssueRecord.model_validate_json(_call("GET", f"/api/issues/{run.issue_id}"))
    try:
        fields = work(brief_model.model_validate_json(issue.description))
    except (ValidationError, IndexError) as error:
        print(f"brief unusable: {type(error).__name__}", file=sys.stderr)
        return _BRIEF_ERROR
    try:
        output: BaseModel = model.model_validate(fields)
    except ValidationError as error:
        print(f"output does not fit its schema: {type(error).__name__}", file=sys.stderr)
        return _SCHEMA_ERROR
    text = output.model_dump_json()
    _call("POST", f"/api/issues/{run.issue_id}/comments", {"body": text})
    _call("PATCH", f"/api/issues/{run.issue_id}", {"status": "done"})
    print(text)
    return 0
