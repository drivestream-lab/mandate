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
from typing import Any

from pydantic import BaseModel

from src.models.role_output_models import RoleOutput

_BRIEF_ERROR = 2
_SCHEMA_ERROR = 3


def _call(method: str, path: str, body: dict[str, object] | None = None) -> dict[str, object]:
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
        return json.load(response)


def run_scripted_step[M: RoleOutput](
    model: type[M], work: Callable[[dict[str, Any]], dict[str, Any]]
) -> int:
    """Read the brief on this run's issue, build the output, check it, and hand it back.

    `work` turns the brief (the issue description, JSON) into the output's fields. An output that
    does not fit `model` is not posted and the script exits non-zero: it counts as missing.
    """
    run = _call("GET", f"/api/heartbeat-runs/{os.environ['PAPERCLIP_RUN_ID']}")
    issue_id = str(run["issueId"])
    issue = _call("GET", f"/api/issues/{issue_id}")
    try:
        brief = json.loads(str(issue["description"]))
        fields = work(brief)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        print(f"brief unusable: {type(error).__name__}", file=sys.stderr)
        return _BRIEF_ERROR
    try:
        output: BaseModel = model.model_validate(fields)
    except ValueError as error:
        print(f"output does not fit its schema: {type(error).__name__}", file=sys.stderr)
        return _SCHEMA_ERROR
    text = output.model_dump_json()
    _call("POST", f"/api/issues/{issue_id}/comments", {"body": text})
    _call("PATCH", f"/api/issues/{issue_id}", {"status": "done"})
    print(text)
    return 0
