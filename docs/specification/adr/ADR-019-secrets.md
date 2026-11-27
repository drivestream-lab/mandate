# ADR-019: Secrets

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-7 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Secret values live outside every repo in `~/.mandate/secrets/<env>/` and reach the Compose stack as Docker secrets. `AppSettings` (per the rules) reads file paths, never values, and fails at startup if a file is missing; `.env.example` lists the paths. Each environment (lab, test) has its own GitHub App installation and private key and its own Paperclip identity token; the test installation is limited to the sandbox repos, so a test run cannot merge into Conduit. Agent workspaces never mount the secrets directory. Held this way: the GitHub App private key, the Mandate Paperclip identity token, and the Mandate and Temporal database credentials. On a later always-on host, the same paths map onto that host's secret store.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
