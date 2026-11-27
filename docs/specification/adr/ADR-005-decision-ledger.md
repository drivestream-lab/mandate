# ADR-005: Decision ledger

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-5 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

A hash-chained, append-only ledger separate from working state, holding decisions, sealed calls, promotions, demotions, emergency merges and policy changes, each with evidence hashes; a signed checkpoint of the chain, including the current policy hash, committed daily and signed by an artifact attestation from a workflow in `mandate-meta`

## Why

Tampering is detectable even by database administrators; exports can be verified by auditors

## Serves

REQ-54, 55, 93 to 95, 107

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
