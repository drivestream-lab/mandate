#!/usr/bin/env bash
# Mint a GitHub App installation token for one swarm role (engineering-ready PRD PL-16).
#
#   scripts/swarm/app_token.sh builder      -> mandate-builder    (push, open PRs, merge into develop)
#   scripts/swarm/app_token.sh challenger   -> mandate-challenger (Approve or findings on a head)
#
# Each role reads only its own folder, ~/.mandate/secrets/build/<app>/ (app-id,
# installation-id, private-key.pem). The runner's folder is never read here: only the
# runner posts mandate/build-verified.
#
# The token is scoped to the repos the swarm builds (mandate, mandate-control-tower), so
# a swarm role cannot write to mandate-verify or mandate-meta even though the App is
# installed org-wide. It goes to stdout only, for one process (git or gh); it is never
# written to disk or logged. Tokens last one hour; callers mint a fresh one per use.
set -euo pipefail

role="${1:-}"
case "$role" in
  builder) app="mandate-builder" ;;
  challenger) app="mandate-challenger" ;;
  *)
    echo "usage: app_token.sh builder|challenger" >&2
    exit 2
    ;;
esac

secrets_root="${MANDATE_BUILD_SECRETS_DIR:-$HOME/.mandate/secrets/build}"
dir="$secrets_root/$app"
for f in app-id installation-id private-key.pem; do
  if [[ ! -r "$dir/$f" ]]; then
    echo "app_token.sh: $dir/$f is missing or unreadable" >&2
    exit 1
  fi
done

app_id="$(tr -d '[:space:]' <"$dir/app-id")"
installation_id="$(tr -d '[:space:]' <"$dir/installation-id")"
repos_json="${MANDATE_SWARM_REPOS_JSON:-[\"mandate\",\"mandate-control-tower\"]}"

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

now="$(date +%s)"
header="$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)"
payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$app_id" | b64url)"
signature="$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$dir/private-key.pem" -binary | b64url)"
jwt="$header.$payload.$signature"

response="$(
  curl -fsS -X POST \
    -H "Authorization: Bearer $jwt" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    -d "{\"repositories\":$repos_json}" \
    "https://api.github.com/app/installations/$installation_id/access_tokens"
)" || {
  echo "app_token.sh: GitHub refused a token for $app" >&2
  exit 1
}

printf '%s' "$response" | python3 -I -c 'import json, sys; print(json.load(sys.stdin)["token"])'
