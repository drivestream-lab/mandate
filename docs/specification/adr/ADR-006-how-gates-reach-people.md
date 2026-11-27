# ADR-006: How gates reach people

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-6 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

On the gate's pull request, as the delivery workflow defines. The signoff is three artifacts on the current head: the gate's label (`impact-map-lgtm`, `spec-lgtm`, `wave-accepted`), an Approve carrying the attestation (initiative, head SHA, digests, artifact paths) and the PR marked ready. At L0 the human holder signs on GitHub; Mandate posts the brief on the PR without the deciding role's call, and the call lives only in Mandate's ledger (sealed before the human signs, revealed after), never as a PR comment or review before the signoff. At L2 and L3 the deciding role signs and Mandate's App applies the three artifacts. Non-merge decisions are made as a review on the pull request when there is one, otherwise as a Paperclip question, with the call sealed first either way. Paperclip's inbox carries those questions, product questions and escalations; Paperclip's own decision model stays off

## Why

Keeps the team's existing workflow and GitHub surface; blind-first holds because nothing on the PR shows the deciding role's call before the holder signs

## Serves

REQ-39, 86, 103

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
