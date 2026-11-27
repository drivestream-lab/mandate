#!/usr/bin/env bash
# Merge one PR as mandate-builder, pinned to the head the runner graded.
#
#   scripts/swarm/merge_task.sh drivestream-lab/mandate 42
#
# Merges a task PR into develop, or the wave PR from develop into main. Refuses unless:
#   - the PR is open, and its base is develop, or main with head develop;
#   - the latest mandate/build-verified status on the head is success, posted by
#     mandate-runner[bot].
# The runner encodes every review rule (challengers, protected paths, the wave signoff,
# the develop-red freeze and its fix exception), so a green status from it is the only
# thing that lets a merge through. The merge API call pins sha to that head, so a push
# after grading fails the merge. No person's account is used (KD, 27 Nov 2026).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="${1:?usage: merge_task.sh OWNER/REPO PR}"
pr="${2:?usage: merge_task.sh OWNER/REPO PR}"
gh_b() { "$here/as_role.sh" builder gh "$@"; }

read -r state base head_ref head < <(gh_b api "repos/$repo/pulls/$pr" -q '"\(.state) \(.base.ref) \(.head.ref) \(.head.sha)"')

[[ "$state" == "open" ]] || { echo "refused: PR $pr is $state" >&2; exit 1; }
if [[ "$base" != "develop" ]] && ! [[ "$base" == "main" && "$head_ref" == "develop" ]]; then
  echo "refused: $head_ref into $base; the builder merges task PRs into develop and develop into main only" >&2
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
