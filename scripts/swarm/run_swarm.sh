#!/usr/bin/env bash
# make swarm: a plain loop that starts one headless Claude Code lead per round (PL-16 BP-7).
#
# The lead is stateless. Each round it rebuilds its state from GitHub and the repos
# (WorkManifest, as-built table, PR states and statuses, the pinned build-log issue),
# acts, appends one build-log entry and exits. Killing this loop, a crash, sleep or a
# context limit loses nothing: run `make swarm` again and the next round resumes from
# repo state.
#
# Settings (environment):
#   SWARM_INTERVAL_SECONDS  pause between rounds (default 300)
#   SWARM_ROUND_BUDGET_USD  hard cap per round, passed to claude --max-budget-usd (default 150)
#   SWARM_LEAD_MODEL        the lead's model (default claude-opus-5-5)
#   SWARM_ONCE=1            run one round and exit (used for the dry run)
#
# Stop: `make swarm-stop` (touches the stop file), or Ctrl-C.
# State outside the repos (never secrets): ~/.mandate/swarm/ holds round logs and spend.tsv.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
state_dir="${MANDATE_SWARM_DIR:-$HOME/.mandate/swarm}"
interval="${SWARM_INTERVAL_SECONDS:-300}"
budget="${SWARM_ROUND_BUDGET_USD:-150}"
model="${SWARM_LEAD_MODEL:-claude-opus-5-5}"
mkdir -p "$state_dir/logs"
stop_file="$state_dir/STOP"
lock_dir="$state_dir/lock"

# One loop at a time. A stale lock (its process gone) is taken over.
if ! mkdir "$lock_dir" 2>/dev/null; then
  old="$(cat "$lock_dir/pid" 2>/dev/null || true)"
  if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
    echo "make swarm is already running (pid $old)" >&2
    exit 1
  fi
  echo "taking over a stale swarm lock (pid ${old:-unknown})"
fi
echo $$ >"$lock_dir/pid"
trap 'rm -rf "$lock_dir"' EXIT
rm -f "$stop_file"

prompt_file="$repo_root/scripts/swarm/lead_round.md"
round=0
while :; do
  [[ -e "$stop_file" ]] && { echo "stop file found; exiting"; break; }
  round=$((round + 1))
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  log="$state_dir/logs/round-$ts.jsonl"
  echo "[$ts] round $round: starting lead ($model, cap \$$budget), log $log"

  # GITHUB_TOKEN holds KD's own token on this machine: the lead and everything it
  # starts must never see it. Swarm roles authenticate through scripts/swarm/as_role.sh.
  set +e
  (
    cd "$repo_root"
    env -u GITHUB_TOKEN -u GH_TOKEN \
      SWARM_ROUND_ID="$ts" SWARM_STATE_DIR="$state_dir" \
      claude -p "$(cat "$prompt_file")" \
      --model "$model" \
      --permission-mode auto \
      --max-budget-usd "$budget" \
      --add-dir "$repo_root/../mandate-meta" "$repo_root/../mandate-control-tower" \
      --output-format stream-json --verbose
  ) >"$log" 2>&1
  code=$?
  set -e

  cost="$(python3 -I -c '
import json, sys
cost = 0.0
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("type") == "result":
        cost = float(event.get("total_cost_usd") or 0.0)
print(f"{cost:.2f}")
' "$log")"
  printf '%s\t%s\t%s\n' "$ts" "$cost" "$code" >>"$state_dir/spend.tsv"
  echo "[$ts] round $round: exit $code, spend \$$cost"

  [[ "${SWARM_ONCE:-0}" == "1" ]] && break
  sleep "$interval"
done
