# ADR-002: How Mandate learns what happened

- Status: accepted
- Date: 19 Nov 2026 (amended 21 Nov 2026 where noted)
- Source: AD-2 in `mandate-meta/prd/INIT-MANDATE-001-engineering.md`

## Decision

Events trigger, state is truth: the plugin forwards Paperclip events; GitHub is polled by the sweep at first, with webhook ingress built, tested and kept disabled behind a policy switch until Mandate has a public endpoint; Mandate reads current state before acting; every action is safe to repeat; a sweep (default every minute) reconciles expected and actual state

## Why

Paperclip events reach only plugins, at least once, without ordering; Paperclip itself reconciles; meets nothing-lost and 1-minute responsiveness together

## Serves

REQ-21, 90 to 92

## Changing this decision

ADRs are immutable. A change is a new ADR that supersedes this one; update the engineering-ready PRD in the same pull request.
