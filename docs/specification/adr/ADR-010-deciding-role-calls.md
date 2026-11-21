# ADR-010: Deciding-role calls

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-10 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

The deciding role receives the same brief as the human, without the author's recommendation, runs as a Paperclip task, returns a structured call (option, reasons, evidence cited); Mandate seals it in the ledger before the human decision opens and reveals it after; a missing or invalid call is retried once, then counts as no call

## Why

Independent, tamper-proof agreement data; the agent-side twin of blind-first

## Serves

REQ-46, 47, 105, 118

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
