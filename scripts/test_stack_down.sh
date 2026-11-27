#!/usr/bin/env bash
# Remove one run's journey stack: containers, network and volumes. Safe to call twice.
#
#   scripts/test_stack_down.sh <run-id>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
run_id="${1:?usage: test_stack_down.sh <run-id>}"
[[ "$run_id" =~ ^[a-z0-9]{4,32}$ ]] || { echo "test_stack_down.sh: bad run id" >&2; exit 2; }

# down reads the same file, so the required variables need a value; none is used.
export STACK_DB_PASSWORD="unused" STACK_AUTH_SECRET="unused" STACK_SIGNING_SECRET="unused"
docker compose -p "mandate-journey-$run_id" -f "$here/../docker/docker-compose.test-stack.yml" \
  down -v --remove-orphans
