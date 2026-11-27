#!/usr/bin/env bash
# Run git or gh as one swarm role, never as the human's own identity.
#
#   scripts/swarm/as_role.sh builder git push -u origin HEAD
#   scripts/swarm/as_role.sh builder gh pr create --base develop ...
#   scripts/swarm/as_role.sh challenger gh api -X POST repos/OWNER/REPO/pulls/N/reviews ...
#
# gh: GITHUB_TOKEN is removed (on KD's machine it holds KD's own token) and GH_TOKEN is a
# fresh installation token of the role's App.
# git: commits are authored and committed as the role's bot, and pushes authenticate
# through git-credential-mandate-app. The helper chain is reset first, so no keychain
# credential of the human is ever used.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
role="${1:-}"
tool="${2:-}"
shift 2 || true

case "$role" in
  builder) bot="mandate-builder[bot]" ; bot_id="359484623" ;;
  challenger) bot="mandate-challenger[bot]" ; bot_id="359484903" ;;
  *)
    echo "usage: as_role.sh builder|challenger git|gh <args...>" >&2
    exit 2
    ;;
esac
email="${bot_id}+${bot}@users.noreply.github.com"

case "$tool" in
  gh)
    token="$("$here/app_token.sh" "$role")"
    exec env -u GITHUB_TOKEN GH_TOKEN="$token" gh "$@"
    ;;
  git)
    exec env -u GITHUB_TOKEN \
      GIT_AUTHOR_NAME="$bot" GIT_AUTHOR_EMAIL="$email" \
      GIT_COMMITTER_NAME="$bot" GIT_COMMITTER_EMAIL="$email" \
      git -c credential.helper= \
      -c "credential.helper=!$here/git-credential-mandate-app $role" \
      -c credential.useHttpPath=false \
      "$@"
    ;;
  *)
    echo "usage: as_role.sh builder|challenger git|gh <args...>" >&2
    exit 2
    ;;
esac
