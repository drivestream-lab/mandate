# ADR-007: Run-signed evidence

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-7 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

A central reusable GitHub Actions workflow in `mandate-verify`, called by each governed repo's caller workflow at a pinned tag, builds the exact commit into a clean environment, runs the protected test set fixed at spec sign-off, and signs the evidence bundle with an artifact attestation (governed repos are public). GitHub Free cannot force a workflow to run, so enforcement sits in Mandate: it accepts evidence only when the attestation's signer workflow is `mandate-verify` at the pinned tag (`--signer-workflow`), with matching commit and test-set digest, and only then posts the required check `mandate/gate-decision`. A PR that edits its CI gets no valid attestation, so the check never posts and the ruleset blocks the merge

## Why

The signer is outside the reach of everyone it judges, without turning Mandate into a CI system

## Serves

REQ-59 to 62, 108

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
