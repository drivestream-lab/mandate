# ADR-021: Pull requests within a wave

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-9 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

One PR per task: one requirement or a small, tightly linked group, with spec, tests and as-built updated together; guide size about 400 changed lines, excluding generated code. Branches follow Launchpad's enforced branching policy: `feature/INIT-MANDATE-001-w<n>-<task-slug>` into `develop`, with `fix/`, `hotfix/` and `chore/` as Launchpad defines them; the WorkManifest in the implementation plan lists the tasks per wave. Each PR passes `make check` and `make test` locally, and `make journeys` for every journey it touches, with the output attached; the PR names the initiative, issue, spec paths and verify command, and the human review is recorded in the ledger's format (REQ-120). A wave closes when all its tasks have merged and its full journey set passes live.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
