# Tests for mandate

## Structure

```
tests/
  unit/        Pure unit tests — no real infra, no network calls.
               Run: make test
  verify/      Live verify scripts (run by `make verify` against a deployed stack).
  journeys/    End-to-end journeys on the local ephemeral stack.
               Run: make journeys   (or: make journeys -- tests/journeys/<file>.py)
  _helpers/    Shared fixtures and helpers (e.g. verify preflight).
```

## Running

```bash
# Unit only (CI gate)
make check && make test

# Live verify (integration) — run scripts directly when added:
# docker-compose -f docker/docker-compose.yml up -d
# .venv/bin/python -m tests.verify.verify_health
```

## Requirement markers

A test covers a requirement with `@pytest.mark.req("REQ-nn")`. In `make test`
(`--require-req-coverage`), every requirement whose row in
`docs/specification/as-built/requirements.md` is not `not started` must have at least one
such test, or the run stops and names the missing requirements.
