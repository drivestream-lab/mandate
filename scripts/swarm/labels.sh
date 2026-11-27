#!/usr/bin/env bash
# Create or update the labels the build flow uses, as mandate-builder (PL-16).
#
#   scripts/swarm/labels.sh [OWNER/REPO ...]   default: drivestream-lab/mandate drivestream-lab/mandate-control-tower
#
#   build-log      the pinned build-log issue (CLAUDE.md, "The build log")
#   wave-accepted  a wave PR from develop into main, accepted after the verifier checked the evidence
#   develop-red    opened by mandate-runner when a develop run is red; freezes task merges
#
# Idempotent: an existing label gets its colour and description updated.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repos=("$@")
[[ ${#repos[@]} -gt 0 ]] || repos=(drivestream-lab/mandate drivestream-lab/mandate-control-tower)

labels=(
  "build-log|5319E7|The pinned build log of INIT-MANDATE-001"
  "wave-accepted|0E8A16|Wave PR accepted after the verifier checked the deployed evidence"
  "develop-red|B60205|develop run is red: task merges are frozen (opened by mandate-runner)"
)

for repo in "${repos[@]}"; do
  for entry in "${labels[@]}"; do
    IFS='|' read -r name color description <<<"$entry"
    "$here/as_role.sh" builder gh label create "$name" --repo "$repo" --color "$color" \
      --description "$description" --force >/dev/null
    echo "$repo: $name"
  done
done
