# Journeys

Journeys run against the real sandbox repos and a real ephemeral stack. Run them with
`make journeys ARGS="tests/journeys/<folder>"`, always without KD's token.

## Signing a gate (tests/journeys/sign_a_gate)

Three identities, all GitHub Apps: Mandate's own test App (reads and posts the check), the
author `mandate-builder` (opens the pull requests) and the signer `mandate-challenger` (holds the
sandbox gates at L0 in the test gate configuration). The author and signer tokens come from the
environment; the test never reads a private key under `~/.mandate/secrets/build`. Mint them with
the swarm script and run:

```bash
R='["mandate-sandbox-meta","mandate-sandbox-svc"]'
MANDATE_JOURNEY_SIGNER_TOKEN="$(MANDATE_SWARM_REPOS_JSON=$R scripts/swarm/app_token.sh challenger)" \
MANDATE_JOURNEY_AUTHOR_TOKEN="$(MANDATE_SWARM_REPOS_JSON=$R scripts/swarm/app_token.sh builder)" \
env -u GITHUB_TOKEN -u GH_TOKEN make journeys ARGS="tests/journeys/sign_a_gate"
```

A missing token fails the run at once. Installation tokens last one hour.
