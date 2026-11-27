#!/usr/bin/env bash
# Merge one task PR into develop as mandate-builder, pinned to the head the runner graded.
#
#   scripts/swarm/merge_task.sh drivestream-lab/mandate 42
#
# Refuses unless every one of these holds on the current head:
#   - the base is develop (the builder never merges into main);
#   - the latest mandate/build-verified status on the head is success, posted by
#     mandate-runner[bot] (the runner encodes the review rules: challengers, KD on
#     protected paths, the develop-red freeze);
#   - no develop-red issue opened by the runner is open on mandate.
# The merge API call pins sha to that head, so a push after grading fails the merge.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="${1:?usage: merge_task.sh OWNER/REPO PR}"
pr="${2:?usage: merge_task.sh OWNER/REPO PR}"
gh_b() { "$here/as_role.sh" builder gh "$@"; }

base="$(gh_b api "repos/$repo/pulls/$pr" -q .base.ref)"
head="$(gh_b api "repos/$repo/pulls/$pr" -q .head.sha)"
state="$(gh_b api "repos/$repo/pulls/$pr" -q .state)"

[[ "$state" == "open" ]] || { echo "refused: PR $pr is $state" >&2; exit 1; }
[[ "$base" == "develop" ]] || { echo "refused: base is $base, the builder merges into develop only" >&2; exit 1; }

# Statuses come newest first; the first one for the context is the current one.
status="$(gh_b api "repos/$repo/commits/$head/statuses?per_page=100" \
  -q '[.[] | select(.context == "mandate/build-verified")][0] | "\(.state) \(.creator.login)"')"
if [[ "$status" != "success mandate-runner[bot]" ]]; then
  echo "refused: mandate/build-verified on ${head:0:12} is '${status:-missing}'" >&2
  exit 1
fi

red="$(gh_b api "repos/drivestream-lab/mandate/issues?state=open&labels=develop-red&per_page=100" \
  -q '[.[] | select(.user.login == "mandate-runner[bot]")] | length')"
if [[ "$red" != "0" ]]; then
  echo "refused: develop is red ($red open develop-red issue(s) on mandate)" >&2
  exit 1
fi

gh_b api -X PUT "repos/$repo/pulls/$pr/merge" -f sha="$head" -f merge_method=merge -q '.sha' >/dev/null
echo "merged $repo#$pr at ${head:0:12}"
