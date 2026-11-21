# ADR-003: How workflows run

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-3 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

One generic runner arranging a fixed set of tested building blocks: agent step, gate, fan-out per repo, wave loop, wait for evidence, timer, park. The pinned contract only arranges blocks; each contract version declares the block versions it needs

## Why

Workflows stay data where they change; behaviour stays tested code where correctness matters

## Serves

REQ-21 to 25, 114

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
