"""Live verify: health with real Postgres and Redis, against the deployed service.

The steps of tests/verify/01-health-detailed.md, run against MANDATE_SERVICE_URL (what
`make deploy` started, or the lab's deployed service after a merge into develop).

Standard library only, so it runs before or without the project's virtualenv. Proxies
are ignored: the service is always on a local or lab network.
"""

import json
import os
import sys
import urllib.error
import urllib.request

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get(url: str) -> tuple[int, str]:
    try:
        with _OPENER.open(url, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def main() -> int:
    base = os.environ.get("MANDATE_SERVICE_URL", "").rstrip("/")
    if not base:
        print("MANDATE_SERVICE_URL is not set", file=sys.stderr)
        return 2
    failures: list[str] = []

    status, body = _get(f"{base}/health")
    if status != 200 or json.loads(body).get("status") != "ok":
        failures.append(f"GET /health: {status} {body[:200]}")
    else:
        print("ok: /health answers status ok")

    status, body = _get(f"{base}/health?detailed=true")
    services = json.loads(body).get("services", {}) if status == 200 else {}
    down = [name for name in ("postgres", "redis") if services.get(name, {}).get("status") != "up"]
    if status != 200 or down:
        failures.append(f"GET /health?detailed=true: {status}, not up: {', '.join(down) or 'none'}")
    else:
        print("ok: postgres and redis are up")

    status, _ = _get(f"{base}/api/v1/")
    if status != 401:
        failures.append(f"GET /api/v1/ without a token: {status}, expected 401")
    else:
        print("ok: /api/v1/ refuses a request without a token (401)")

    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
