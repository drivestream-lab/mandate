#!/usr/bin/env bash
# Merge one PR as mandate-builder, pinned to the head the runner graded.
#
#   scripts/swarm/merge_task.sh drivestream-lab/mandate 42
#
# Merges a task PR into develop. Refuses unless:
#   - the PR is open, its base is develop, and its head branch is in this repo;
#   - the latest mandate/build-verified status on the head is success, posted by
#     mandate-runner[bot].
# Nothing merges into main: KD decided on 27 Nov 2026 that main is left alone for now.
# When that changes, a main merge must also refuse while a develop-red issue is open,
# because the runner freezes only PRs into develop.
# The runner encodes every review rule (challengers, protected paths, the wave signoff,
# the develop-red freeze and its fix exception), so a green status from it is the only
# thing that lets a merge through. The merge API call pins sha to that head, so a push
# after grading fails the merge. No person's account is used (KD, 27 Nov 2026).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="${1:?usage: merge_task.sh OWNER/REPO PR}"
pr="${2:?usage: merge_task.sh OWNER/REPO PR}"
gh_b() { "$here/as_role.sh" builder gh "$@"; }

read -r state base head_ref head_repo head < <(gh_b api "repos/$repo/pulls/$pr" \
  -q '"\(.state) \(.base.ref) \(.head.ref) \(.head.repo.full_name) \(.head.sha)"')

[[ "$state" == "open" ]] || { echo "refused: PR $pr is $state" >&2; exit 1; }
if [[ "$base" != "develop" ]]; then
  echo "refused: base is $base; the builder merges into develop only (nothing into main, KD)" >&2
  exit 1
fi
if [[ "$head_repo" != "$repo" ]]; then
  echo "refused: head is from $head_repo, not $repo" >&2
  exit 1
fi

# Statuses come newest first; the first one for the context is the current one.
status="$(gh_b api "repos/$repo/commits/$head/statuses?per_page=100" \
  -q '[.[] | select(.context == "mandate/build-verified")][0] | "\(.state) \(.creator.login)"')"
if [[ "$status" != "success mandate-runner[bot]" ]]; then
  echo "refused: mandate/build-verified on ${head:0:12} is '${status:-missing}'" >&2
  exit 1
fi

gh_b api -X PUT "repos/$repo/pulls/$pr/merge" -f sha="$head" -f merge_method=merge -q '.sha' >/dev/null
echo "merged $repo#$pr ($head_ref into $base) at ${head:0:12}"
