# ADR-001: Who owns a work item's state

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-1 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Split by field. Mandate owns workflow position, gate holders, signoffs, evidence and rungs; collaboration fields stay native to Paperclip. **A gate is a merge into `develop`** (and `develop` into `main`): the PRD, the spec, each wave and the closure purges. Nothing else blocks; every other decision (technical review, triage, hiring, outline acceptance) is recorded in the ledger without stopping work (a recorded no fails the next downstream merge until resolved), and upstream changes mark downstream work `-stale` or `-revised` as the workflow already does. Paperclip carries the agents' work, questions and escalations; it holds no gate

## Why

First principles (21 Nov 2026): only unverified work becoming irreversible needs a hard stop, and in the delivery workflow that is a merge into `develop`. Enforcing gates through Paperclip approval stages or extra GitHub rules added failure modes (board overrides, plan limits) without protecting anything a merge check does not already protect

## Serves

REQ-23, 40, 42, 43

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
