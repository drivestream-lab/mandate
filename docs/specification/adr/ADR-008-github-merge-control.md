# ADR-008: GitHub merge control

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-8 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

One required check on `develop` and `main`: `mandate/gate-decision`, which Mandate posts only when the gate's label, attested approval and ready state all match the PR's current head, the signer held the gate at its rung, the decision is in the ledger, and (for waves) the run-signed evidence verifies. A push after signoff voids it (the workflow's `-revised`). Who presses merge follows the workflow (PM for the PRD, engineering for spec and waves); at L2 and L3 Mandate's App merges. No other branch rule is needed

## Why

Exactly the verified commit by construction at Conduit's early load

## Serves

REQ-63, 109, 121, 122

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
