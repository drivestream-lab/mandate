#!/usr/bin/env bash
# Start the ephemeral journey stack for one run.
#
#   scripts/test_stack_up.sh <run-id>
#
# The Compose project is mandate-journey-<run-id>, so concurrent runs share nothing. Host
# ports are picked by Docker. On success, stdout carries only KEY=VALUE lines of non-secret
# connection details (project, URLs, ports). Passwords come from STACK_DB_PASSWORD, set by
# the caller; the auth and signing secrets are generated here for this run only and never
# written to disk or printed. On failure the half-started stack is removed.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
compose_file="$here/../docker/docker-compose.test-stack.yml"
run_id="${1:?usage: test_stack_up.sh <run-id>}"
[[ "$run_id" =~ ^[a-z0-9]{4,32}$ ]] || { echo "test_stack_up.sh: bad run id" >&2; exit 2; }
: "${STACK_DB_PASSWORD:?test_stack_up.sh: STACK_DB_PASSWORD must be set}"

project="mandate-journey-$run_id"
export STACK_AUTH_SECRET="${STACK_AUTH_SECRET:-$(openssl rand -hex 32)}"
export STACK_SIGNING_SECRET="${STACK_SIGNING_SECRET:-$(openssl rand -hex 32)}"
compose=(docker compose -p "$project" -f "$compose_file")

if ! "${compose[@]}" up -d --wait --wait-timeout 240 >&2; then
  echo "test_stack_up.sh: the stack did not become healthy; logs follow" >&2
  "${compose[@]}" logs --no-color --tail 40 2>&1 \
    | sed -E 's#(postgres://[^:]+:)[^@]+@#\1<redacted>@#g' >&2 || true
  "$here/test_stack_down.sh" "$run_id" >&2 || true
  exit 1
fi

port_of() { "${compose[@]}" port "$1" "$2" | sed -E 's/.*://'; }
echo "STACK_PROJECT=$project"
echo "PAPERCLIP_URL=http://127.0.0.1:$(port_of paperclip 3100)"
echo "POSTGRES_PORT=$(port_of postgres 5432)"
echo "TEMPORAL_ADDRESS=127.0.0.1:$(port_of temporal 7233)"
