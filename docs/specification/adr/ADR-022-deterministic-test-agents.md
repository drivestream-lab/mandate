# ADR-022: Deterministic test agents

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: PL-10 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Real Paperclip agents on Paperclip's built-in `process` adapter, running Python scripts from `mandate/tests/agents/`. The scripts reuse Mandate's `models/` for their output schemas, so a schema change breaks them in the same PR; one script per end-to-end flow names each role's scripted step; agent identities are created per run in the ephemeral Paperclip. No new adapter and no new repo.

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
