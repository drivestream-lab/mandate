# ADR-011: Codebase context

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-11 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

A separate Python service, `mandate-context`: an MCP gateway in front of pluggable engines (level 0 pass-through, level 2 Serena, higher later), indexing per commit, sending Mandate a usage record for every answer; agents fall back to level 0 when it is down

## Why

Governance stays independent of the heaviest, most experimental part

## Serves

REQ-34 to 38

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
