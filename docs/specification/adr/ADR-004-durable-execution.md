# ADR-004: Durable execution

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-4 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Work-item state, pinned versions and timers are rows in Mandate's Postgres; timers fire from the sweep. Self-hosted Temporal (persisting to Postgres) runs only short step workflows. Idempotency keys on every step; an outbox for every state change that leaves Mandate

## Why

Weeks-long work never replays history across Mandate upgrades; Temporal's maturity and tooling for the risky, exactly-once moments

## Serves

REQ-90 to 92, 113, 114

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
