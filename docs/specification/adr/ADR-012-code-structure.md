# ADR-012: Code structure

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-12 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

A modular monolith in `mandate`: one package per capability with small public interfaces and an enforced import-boundary check; the API, Temporal workers and the sweep run as separate processes from the same code. The control tower is a thin TypeScript plugin holding no state

## Why

Small enforced seams for Claude Code; one database keeps the outbox and idempotency rules simple

## Serves

All

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
